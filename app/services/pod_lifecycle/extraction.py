"""
POD PDF → per-page vision extraction and reconciliation.

Ported from ``old/agents/pod_validator/pod_processing.py`` (prompts and
reconciliation rules preserved). Vision calls use ``chat_vision_json`` with the
app's LLM_* settings instead of the legacy AsyncOpenAI streaming client.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pdf2image import convert_from_path
from PIL import Image, UnidentifiedImageError

from app.core.config import settings
from app.integrations.langsmith import RenderedPrompt
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_pod_vision_prompts
from app.tools.llm_client import LLMClientError, chat_vision_json

logger = logging.getLogger(__name__)

# Finite bomb limit (was None and allowed huge MediaBox@200DPI conversions to OOM).
# ~89M pixels ≈ 268 MB RGB; Tracy native pages are ~8M.
Image.MAX_IMAGE_PIXELS = settings.POD_MAX_IMAGE_PIXELS

# Letter longest side ~792pt; phone/scan PDFs that set MediaBox=pixel dims are far larger.
_PATHOLOGICAL_MEDIABOX_PT = 1200.0


class PodPdfTooLargeError(Exception):
    """PDF would use too much memory to convert for analysis; fail closed before OOM/SIGKILL."""

    error_key = "pod_pdf_too_large"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _resize_for_vision(image: Image.Image, max_side_px: int) -> Image.Image:
    """Downscale image so the longest side is <= max_side_px (keeps aspect ratio)."""
    if not max_side_px or max_side_px <= 0:
        return image
    w, h = image.size
    longest = max(w, h)
    if longest <= max_side_px:
        return image
    scale = max_side_px / float(longest)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return image.resize((new_w, new_h), resample=Image.LANCZOS)


def _rgb_bytes(width: int, height: int) -> int:
    return max(0, int(width)) * max(0, int(height)) * 3


def _save_vision_jpeg(
    image: Image.Image,
    image_path: str,
    *,
    max_side_px: int,
    jpeg_quality: int,
) -> None:
    prepared = _resize_for_vision(image.convert("RGB"), max_side_px=max_side_px)
    prepared.save(
        image_path,
        "JPEG",
        quality=max(25, min(95, int(jpeg_quality))),
        optimize=True,
        progressive=True,
    )


def _page_mediabox_pts(page: Any) -> tuple[float, float]:
    box = page.mediabox
    return float(box[2] - box[0]), float(box[3] - box[1])


def _is_pathological_mediabox(width_pt: float, height_pt: float) -> bool:
    return max(width_pt, height_pt) >= _PATHOLOGICAL_MEDIABOX_PT


def _effective_poppler_dpi(
    *,
    requested_dpi: int,
    width_pt: float,
    height_pt: float,
) -> int:
    """
    For phone/scanner PDFs that set MediaBox = pixel size in points, DPI>72
    upscales inventively (e.g. 200/72 ≈ 2.78× per side). Use 72 DPI then.
    """
    if _is_pathological_mediabox(width_pt, height_pt):
        return min(int(requested_dpi), 72)
    return int(requested_dpi)


def _assert_conversion_memory_budget(
    *,
    page_bytes: int,
    total_bytes: int,
    page_number: int,
    max_page_bytes: int,
    max_total_bytes: int,
) -> None:
    if max_page_bytes > 0 and page_bytes > max_page_bytes:
        raise PodPdfTooLargeError(
            f"page {page_number} conversion memory estimate {page_bytes} bytes exceeds "
            f"POD_CONVERT_MAX_PAGE_BYTES={max_page_bytes}"
        )
    if max_total_bytes > 0 and total_bytes > max_total_bytes:
        raise PodPdfTooLargeError(
            f"total conversion memory estimate {total_bytes} bytes exceeds "
            f"POD_CONVERT_MAX_TOTAL_BYTES={max_total_bytes}"
        )


def _try_extract_embedded_page_images(
    pdf_path: str,
    temp_dir: str,
    *,
    max_side_px: int,
    jpeg_quality: int,
    max_pages: int | None,
    max_page_bytes: int,
    max_total_bytes: int,
) -> list[str] | None:
    """
    If every page is a single full-page image XObject (Tracy-class phone/scan PDF),
    extract those images without Poppler MediaBox upscaling. Returns None to fall back.
    """
    try:
        import pikepdf
        from pikepdf import PdfImage
    except ImportError:
        return None

    try:
        with pikepdf.open(pdf_path) as pdf:
            pages = list(pdf.pages)
            if max_pages and max_pages > 0:
                pages = pages[:max_pages]
            if not pages:
                return None

            extracted: list[tuple[int, Any]] = []
            total_bytes = 0
            for index, page in enumerate(pages, start=1):
                images = page.get_images()
                items = list(images.items())
                if len(items) != 1:
                    return None
                _name, obj = items[0]
                pdf_image = PdfImage(obj)
                width_pt, height_pt = _page_mediabox_pts(page)
                # Phone/scan pattern: MediaBox points == image pixel dimensions.
                if (
                    abs(pdf_image.width - width_pt) > max(2.0, 0.05 * width_pt)
                    or abs(pdf_image.height - height_pt) > max(2.0, 0.05 * height_pt)
                ):
                    return None
                page_bytes = _rgb_bytes(pdf_image.width, pdf_image.height)
                total_bytes += page_bytes
                _assert_conversion_memory_budget(
                    page_bytes=page_bytes,
                    total_bytes=total_bytes,
                    page_number=index,
                    max_page_bytes=max_page_bytes,
                    max_total_bytes=max_total_bytes,
                )
                extracted.append((index, pdf_image))

            image_paths: list[str] = []
            for index, pdf_image in extracted:
                image_path = os.path.join(temp_dir, f"page_{index:03d}.jpg")
                pil_image = pdf_image.as_pil_image()
                _save_vision_jpeg(
                    pil_image,
                    image_path,
                    max_side_px=max_side_px,
                    jpeg_quality=jpeg_quality,
                )
                image_paths.append(image_path)

            logger.info(
                "pod_extraction: using embedded page images load_id=%s page_count=%s",
                Path(pdf_path).stem.replace(" POD", "").replace("_", ""),
                len(image_paths),
            )
            return image_paths
    except PodPdfTooLargeError:
        raise
    except Exception:
        logger.info(
            "pod_extraction: embedded page image path unavailable; falling back to Poppler",
            exc_info=True,
        )
        return None


def _convert_pdf_with_poppler_page_at_a_time(
    pdf_path: str,
    temp_dir: str,
    *,
    dpi: int,
    max_side_px: int,
    jpeg_quality: int,
    thread_count: int,
    max_pages: int | None,
    max_page_bytes: int,
    max_total_bytes: int,
) -> list[str]:
    """Rasterize one page at a time; adjust DPI for pathological MediaBox PDFs."""
    try:
        from pdf2image import pdfinfo_from_path
    except Exception:
        pdfinfo_from_path = None  # type: ignore[assignment]

    page_count: int | None = None
    mediaboxes: list[tuple[float, float]] = []
    try:
        import pikepdf

        with pikepdf.open(pdf_path) as pdf:
            pages = list(pdf.pages)
            if max_pages and max_pages > 0:
                pages = pages[:max_pages]
            page_count = len(pages)
            mediaboxes = [_page_mediabox_pts(page) for page in pages]
    except Exception:
        mediaboxes = []
        if pdfinfo_from_path is not None:
            try:
                info = pdfinfo_from_path(pdf_path)
                page_count = int(info.get("Pages") or 0) or None
            except Exception:
                page_count = None

    if page_count is None or page_count < 1:
        # Last resort: single convert with last_page cap (still may OOM — budget below helps).
        last = max_pages if max_pages and max_pages > 0 else None
        images = convert_from_path(
            pdf_path,
            fmt="jpeg",
            dpi=dpi,
            thread_count=max(1, int(thread_count)),
            first_page=1,
            last_page=last,
        )
        if not images:
            raise ValueError(f"No images could be extracted from PDF: {pdf_path}")
        image_paths: list[str] = []
        total_bytes = 0
        for i, image in enumerate(images):
            page_bytes = _rgb_bytes(*image.size)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=i + 1,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
            image_path = os.path.join(temp_dir, f"page_{i + 1:03d}.jpg")
            _save_vision_jpeg(
                image,
                image_path,
                max_side_px=max_side_px,
                jpeg_quality=jpeg_quality,
            )
            image_paths.append(image_path)
        return image_paths

    if max_pages and max_pages > 0:
        page_count = min(page_count, max_pages)

    image_paths = []
    total_bytes = 0
    for page_number in range(1, page_count + 1):
        if mediaboxes and page_number <= len(mediaboxes):
            width_pt, height_pt = mediaboxes[page_number - 1]
            page_dpi = _effective_poppler_dpi(
                requested_dpi=dpi,
                width_pt=width_pt,
                height_pt=height_pt,
            )
            est_w = int(width_pt * page_dpi / 72.0)
            est_h = int(height_pt * page_dpi / 72.0)
            page_bytes = _rgb_bytes(est_w, est_h)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=page_number,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
        else:
            page_dpi = dpi

        images = convert_from_path(
            pdf_path,
            fmt="jpeg",
            dpi=page_dpi,
            thread_count=1,
            first_page=page_number,
            last_page=page_number,
        )
        if not images:
            raise ValueError(
                f"No image extracted from PDF page {page_number}: {pdf_path}"
            )
        image = images[0]
        if not mediaboxes:
            page_bytes = _rgb_bytes(*image.size)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=page_number,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
        image_path = os.path.join(temp_dir, f"page_{page_number:03d}.jpg")
        _save_vision_jpeg(
            image,
            image_path,
            max_side_px=max_side_px,
            jpeg_quality=jpeg_quality,
        )
        image_paths.append(image_path)
        del images, image

    return image_paths


def get_prompt(broker_name=None):
    """
    Returns the inline fallback prompt for the LLM (legacy/tests).

    Prefer ``resolve_pod_vision_prompts`` for Hub-managed prompts.
    """
    from app.domain.vision_prompt_templates import render_inline_pod_prompts

    system, _user = render_inline_pod_prompts(broker_name)
    return system


def reconcile_pod_data(page_results, broker_name=None):
    """
    Takes all page results and uses rule-based engine to determine the final data.
    """
    evidence_map = {}
    reconciliation_log = {}

    load_id = "unknown"
    if page_results:
        load_id = page_results[0].get("load_id", "unknown")

    error_pages = [r for r in page_results if r.get("error")]

    if error_pages:
        error_summary = []
        for error_page in error_pages:
            page_num = error_page.get("page_number", "unknown")
            error_msg = error_page.get("error", "Unknown error")
            error_type = error_page.get("error_type", "Unknown")
            error_category = error_page.get("error_category", "unknown")
            error_summary.append(f"Page {page_num}: {error_type} - {error_msg}")

        reconciliation_log["processing_errors"] = (
            f"Failed to process {len(error_pages)}/{len(page_results)} pages: {'; '.join(error_summary)}"
        )
        logger.warning(
            "pod_extraction: POD processing had errors load_id=%s failed=%s total=%s",
            load_id,
            len(error_pages),
            len(page_results),
        )

    for result in page_results:
        if result.get("error") or not result.get("extracted_data"):
            continue
        data = result["extracted_data"]
        for field in data.get("fields", []):
            key = field.get("key")
            if not key:
                continue
            if key not in evidence_map:
                evidence_map[key] = []
            field_value = field.get("value")
            if field_value is None:
                processed_value = None
            else:
                processed_value = str(field_value).strip()

            evidence_map[key].append(
                {
                    "value": processed_value,
                    "page": result["page_number"],
                    "confidence": field.get("confidence", 50),
                    "context": field.get("context_snippet", ""),
                    "page_type": data.get("page_type", "UNKNOWN"),
                }
            )

    final_data = {}

    confidence_threshold = 75

    def filter_broker_name(carriers, broker_name):
        if not broker_name:
            return carriers
        broker_lower = broker_name.lower().strip()
        filtered = [c for c in carriers if broker_lower not in str(c["value"]).lower().strip()]
        if len(filtered) < len(carriers):
            logger.info(
                "pod_extraction: filtered broker from carrier candidates broker=%s removed=%s",
                broker_name,
                [c["value"] for c in carriers if broker_lower in str(c["value"]).lower().strip()],
            )
        return filtered

    carrier_candidates = [
        c for c in evidence_map.get("carrier_name", []) if c["value"] and c["confidence"] >= confidence_threshold
    ]
    carrier_candidates = filter_broker_name(carrier_candidates, broker_name)

    lumper_carriers = [c for c in carrier_candidates if c["page_type"] == "LUMPER_RECEIPT"]

    if lumper_carriers:
        winner = lumper_carriers[0]["value"]
        final_data["carrier_name"] = winner
        reconciliation_log["carrier_name"] = (
            f"Selected '{winner}' as carrier from Lumper Receipt (highest trust)."
        )
    elif carrier_candidates:
        winner = Counter(c["value"] for c in carrier_candidates).most_common(1)[0][0]
        final_data["carrier_name"] = winner
        reconciliation_log["carrier_name"] = f"Selected '{winner}' as carrier by majority vote."
    else:
        final_data["carrier_name"] = None
        broker_note = f" (Note: Broker '{broker_name}' was excluded from carrier selection)" if broker_name else ""
        reconciliation_log["carrier_name"] = f"No valid carrier found on any page{broker_note}."

    po_candidates = evidence_map.get("po_number", [])
    if po_candidates:
        all_pos = set()
        for candidate in po_candidates:
            pos_on_page = [po.strip() for po in str(candidate["value"]).split(",")]
            for po in pos_on_page:
                if po and len(po.strip()) >= 2 and po.strip().lower() not in ["null", "none", "n/a"]:
                    all_pos.add(po)
        if all_pos:
            final_data["po_number"] = ", ".join(sorted(list(all_pos)))
            reconciliation_log["po_number"] = f"Aggregated {len(all_pos)} unique PO number(s) from all pages."

    for key in [
        "pickup_location",
        "pickup_address",
        "destination_location",
        "destination_address",
        "stamp_company_name",
    ]:
        candidates = [c for c in evidence_map.get(key, []) if c["value"]]
        if not candidates:
            continue
        bol_candidates = [c for c in candidates if c["page_type"] == "BILL_OF_LADING"]
        source = bol_candidates if bol_candidates else candidates
        if "address" in key:
            winner_val = max(source, key=lambda x: len(x["value"]))["value"]
        else:
            winner_val = Counter(c["value"] for c in source).most_common(1)[0][0]
        final_data[key] = winner_val
        reconciliation_log[key] = f"Selected '{winner_val}' based on majority/completeness."

    signature_pages = [
        p["page_number"]
        for p in page_results
        if p.get("extracted_data", {}).get("proof_of_receipt", {}).get("has_receiver_signature")
    ]
    stamp_pages = [
        p["page_number"]
        for p in page_results
        if p.get("extracted_data", {}).get("proof_of_receipt", {}).get("has_stamp")
    ]

    final_data["signature_present"] = len(signature_pages) > 0
    final_data["stamp_present"] = len(stamp_pages) > 0

    reconciliation_log["signature_present"] = (
        f"Receiver signature found on page(s): {signature_pages}"
        if final_data["signature_present"]
        else "No valid receiver signature/acceptance found."
    )
    reconciliation_log["stamp_present"] = (
        f"Company stamp found on page(s): {stamp_pages}"
        if final_data["stamp_present"]
        else "No stamp found."
    )

    final_data["delivery_confirmed"] = is_valid_delivery_confirmation(final_data)

    llm_reasoning = []
    for result in page_results:
        if result.get("extracted_data", {}).get("proof_of_receipt", {}).get("delivery_confirmation_reasoning"):
            page_num = result["page_number"]
            reasoning = result["extracted_data"]["proof_of_receipt"]["delivery_confirmation_reasoning"]
            llm_reasoning.append(f"Page {page_num}: {reasoning}")

    final_data["delivery_confirmation_reasoning"] = (
        "; ".join(llm_reasoning) if llm_reasoning else "No delivery confirmation evidence found by LLM"
    )

    stop_times_agg = []
    for result in sorted(page_results, key=lambda r: r.get("page_number", 0)):
        if result.get("error") or not result.get("extracted_data"):
            continue
        raw = result["extracted_data"].get("stop_times")
        if not isinstance(raw, list):
            continue
        for obj in raw:
            if not isinstance(obj, dict):
                continue
            raw_vals = {
                "pickup_checkin_time": obj.get("pickup_checkin_time"),
                "pickup_checkout_time": obj.get("pickup_checkout_time"),
                "delivery_checkin_time": obj.get("delivery_checkin_time"),
                "delivery_checkout_time": obj.get("delivery_checkout_time"),
            }
            normalized = {}
            for k, v in raw_vals.items():
                s = _str_or_empty(v)
                normalized[k] = _normalize_stop_time_to_iso(s) if s else ""
            stop_times_agg.append(normalized)
    final_data["stop_times"] = stop_times_agg
    if stop_times_agg:
        reconciliation_log["stop_times"] = (
            f"Aggregated {len(stop_times_agg)} stop(s) with check-in/check-out times from pages."
        )

    return final_data, reconciliation_log


def _str_or_empty(val):
    """Return non-empty string value or empty string; never None for stop_times fields."""
    if val is None:
        return ""
    s = str(val).strip()
    return s if s and s.lower() not in ("null", "none", "n/a") else ""


def _normalize_stop_time_to_iso(val):
    """
    Normalize a stop_times timestamp to ISO 8601 UTC format: 2026-02-06T07:34:49Z.
    Returns the original string if parsing fails (so we don't drop valid LLM output).
    """
    if not val or not isinstance(val, str):
        return ""
    s = val.strip()
    if not s or s.lower() in ("null", "none", "n/a"):
        return ""
    if s.endswith("Z") and "T" in s and len(s) >= 20:
        return s
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %I:%M %p",
        "%m/%d/%y %H:%M",
        "%m/%d/%Y %H:%M",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
    ):
        try:
            normalized = s.replace("Z", "+00:00")
            if "+" in normalized or "-" in normalized[-6:]:
                dt = datetime.fromisoformat(normalized)
            else:
                dt = datetime.strptime(s.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        except (ValueError, TypeError):
            continue
    return s


def is_valid_delivery_confirmation(data):
    """A delivery is confirmed if there is a valid receiver signature OR a stamp."""
    return data.get("signature_present", False) or data.get("stamp_present", False)


def validate_pod_consistency(final_data):
    """Validates the final reconciled data for logical issues."""
    issues = []
    if not is_valid_delivery_confirmation(final_data):
        issues.append("No concrete proof of delivery (receiver signature or stamp required).")
    return issues


def convert_pdf_to_images(
    pdf_path: str,
    temp_dir: str,
    *,
    dpi: int = 200,
    max_side_px: int = 0,
    jpeg_quality: int = 85,
    thread_count: int = 1,
    max_pages: int | None = None,
) -> list[str]:
    """
    Rasterize PDF to JPEGs under ``temp_dir``, or treat ``pdf_path`` as a single image.

    Prefer embedded full-page images (avoids Poppler MediaBox upscale OOM on phone/scan
    PDFs). Otherwise convert page-at-a-time with pathological-MediaBox DPI clamping and
    a memory budget that raises ``PodPdfTooLargeError`` before SIGKILL.
    """
    load_id = Path(pdf_path).stem.replace(" POD", "").replace("_", "")
    if not max_side_px or max_side_px <= 0:
        max_side_px = settings.POD_IMAGE_MAX_SIDE_PX
    max_page_bytes = settings.POD_CONVERT_MAX_PAGE_BYTES
    max_total_bytes = settings.POD_CONVERT_MAX_TOTAL_BYTES

    logger.info(
        "pod_extraction: preparing POD document for vision pdf_path=%s load_id=%s",
        pdf_path,
        load_id,
    )

    try:
        try:
            with Image.open(pdf_path) as image:
                if str(getattr(image, "format", "")).upper() not in {
                    "JPEG",
                    "JPG",
                    "PNG",
                    "GIF",
                    "WEBP",
                    "BMP",
                    "TIFF",
                }:
                    raise UnidentifiedImageError(
                        f"Unsupported direct image format: {getattr(image, 'format', None)}"
                    )
                image.load()
                image_path = os.path.join(temp_dir, "page_001.jpg")
                _save_vision_jpeg(
                    image,
                    image_path,
                    max_side_px=max_side_px,
                    jpeg_quality=jpeg_quality,
                )
                logger.info(
                    "pod_extraction: image attachment prepared load_id=%s path=%s",
                    load_id,
                    image_path,
                )
                return [image_path]
        except (UnidentifiedImageError, OSError, ValueError):
            pass

        embedded = _try_extract_embedded_page_images(
            pdf_path,
            temp_dir,
            max_side_px=max_side_px,
            jpeg_quality=jpeg_quality,
            max_pages=max_pages,
            max_page_bytes=max_page_bytes,
            max_total_bytes=max_total_bytes,
        )
        if embedded:
            return embedded

        image_paths = _convert_pdf_with_poppler_page_at_a_time(
            pdf_path,
            temp_dir,
            dpi=dpi,
            max_side_px=max_side_px,
            jpeg_quality=jpeg_quality,
            thread_count=thread_count,
            max_pages=max_pages,
            max_page_bytes=max_page_bytes,
            max_total_bytes=max_total_bytes,
        )
        logger.info(
            "pod_extraction: PDF conversion successful load_id=%s page_count=%s",
            load_id,
            len(image_paths),
        )
        return image_paths
    except PodPdfTooLargeError:
        logger.warning(
            "pod_extraction: PDF too large to convert load_id=%s pdf_path=%s",
            load_id,
            pdf_path,
        )
        raise
    except Exception as e:
        error_msg = f"Failed to convert PDF to images: {type(e).__name__}: {str(e)}"
        logger.exception("pod_extraction: PDF conversion failed pdf_path=%s", pdf_path)
        raise Exception(error_msg) from e


def analyze_page(
    image_path: str,
    page_number: int,
    broker_name=None,
    *,
    vision_prompts: RenderedPrompt | None = None,
    prompt_trace: PromptTraceMetadata | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Per-page vision extraction (sync ``chat_vision_json``, same pattern as ratecon)."""
    load_id = Path(image_path).stem
    if vision_prompts is None:
        system_prompt = get_prompt(broker_name)
        user_prompt = " "
    else:
        system_prompt = vision_prompts.system
        user_prompt = vision_prompts.user

    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        extracted_data = chat_vision_json(
            system_prompt,
            user_prompt,
            image_data,
            timeout_s=300.0,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_trace=prompt_trace,
        )
        if not isinstance(extracted_data, dict):
            extracted_data = {}
        return {"page_number": page_number, "extracted_data": extracted_data, "load_id": load_id}
    except LLMClientError as api_e:
        return {
            "page_number": page_number,
            "error": f"API Error: {api_e}",
            "load_id": load_id,
            "error_category": "api_error",
        }
    except Exception as e:
        error_msg = str(e) if str(e) else f"{type(e).__name__}: Exception occurred during page analysis"
        return {
            "page_number": page_number,
            "error": error_msg,
            "error_type": type(e).__name__,
            "load_id": load_id,
            "error_category": "exception",
        }


def extract_from_pdf_path(
    pdf_path: str,
    *,
    broker_name: str | None = None,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
    fast_mode: bool = False,
    max_pages: int | None = None,
) -> tuple[list[Any], dict[str, Any], list[str], dict[str, Any]]:
    """
    Sync pipeline: ``tempfile.mkdtemp`` → PDF/images → per-page ``chat_vision_json`` → reconcile.

    Mirrors ``ratecon_extraction.extract_from_pdf_path`` (no asyncio, no nested event loop).
    Returns ``(page_results, final_pod_data, validation_issues, reconciliation_log)``.
    """
    load_id = Path(pdf_path).stem.replace(" POD", "").replace("_", "")

    from app.domain.prompt_step_keys import POD_PAGE_EXTRACTION

    vision_prompts, prompt_metadata = resolve_pod_vision_prompts(
        tenant_settings,
        broker_name,
    )
    prompt_trace = PromptTraceMetadata.from_load(POD_PAGE_EXTRACTION, prompt_metadata)

    work_dir = tempfile.mkdtemp(prefix="pod_extraction_")
    try:
        default_dpi = settings.POD_IMAGE_DPI
        default_quality = settings.POD_JPEG_QUALITY
        default_max_side = settings.POD_IMAGE_MAX_SIDE_PX
        default_threads = settings.POD_PDF_THREAD_COUNT

        if fast_mode:
            dpi = settings.POD_FAST_IMAGE_DPI
            jpeg_quality = settings.POD_FAST_JPEG_QUALITY
            max_side_px = settings.POD_FAST_IMAGE_MAX_SIDE_PX
            thread_count = settings.POD_FAST_PDF_THREAD_COUNT
            max_tokens = settings.POD_FAST_MAX_TOKENS
        else:
            dpi = default_dpi
            jpeg_quality = default_quality
            max_side_px = default_max_side
            thread_count = default_threads
            max_tokens = None

        try:
            image_paths = convert_pdf_to_images(
                pdf_path,
                work_dir,
                dpi=dpi,
                max_side_px=max_side_px,
                jpeg_quality=jpeg_quality,
                thread_count=thread_count,
                max_pages=max_pages,
            )
        except PodPdfTooLargeError:
            raise
        except Exception as e:
            error_msg = f"Critical processing failure: {type(e).__name__}: {str(e)}"
            logger.exception("pod_extraction: critical PDF processing failure load_id=%s", load_id)
            sorted_results = [
                {
                    "page_number": 1,
                    "timestamp": datetime.now().isoformat(),
                    "error": error_msg,
                    "error_type": type(e).__name__,
                    "load_id": load_id,
                }
            ]
            final_pod_data, reconciliation_log = reconcile_pod_data(sorted_results, broker_name)
            validation_issues = validate_pod_consistency(final_pod_data)
            return sorted_results, final_pod_data, validation_issues, reconciliation_log

        logger.info(
            "pod_extraction: processing PDF pages load_id=%s page_count=%s",
            load_id,
            len(image_paths),
        )

        processed_results: list[dict[str, Any]] = []
        for i, img_path in enumerate(image_paths):
            page_num = i + 1
            result = analyze_page(
                img_path,
                page_num,
                broker_name,
                vision_prompts=vision_prompts,
                prompt_trace=prompt_trace,
                max_tokens=max_tokens,
                temperature=0.0,
            )
            row = {
                **result,
                "timestamp": datetime.now().isoformat(),
            }
            if "load_id" not in row:
                row["load_id"] = load_id
            processed_results.append(row)

        sorted_results = sorted(processed_results, key=lambda x: x["page_number"])

        final_pod_data, reconciliation_log = reconcile_pod_data(sorted_results, broker_name)
        validation_issues = validate_pod_consistency(final_pod_data)

        logger.info(
            "pod_extraction: reconciliation complete load_id=%s pages=%s ok=%s failed=%s model=%s",
            load_id,
            len(sorted_results),
            len([r for r in sorted_results if "error" not in r]),
            len([r for r in sorted_results if "error" in r]),
            model_label,
        )

        if validation_issues:
            logger.warning(
                "pod_extraction: validation issues load_id=%s issues=%s",
                load_id,
                validation_issues,
            )

        return sorted_results, final_pod_data, validation_issues, reconciliation_log
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def pod_confidence_score(
    page_results: list[Any],
    final_pod_data: dict[str, Any],
    validation_issues: list[str],
) -> float:
    """Heuristic 0..1 score from page success rate and delivery confirmation."""
    total = len(page_results) or 1
    ok = sum(1 for r in page_results if r.get("extracted_data") and not r.get("error"))
    ratio = ok / total
    if final_pod_data.get("delivery_confirmed"):
        base = 0.35 + 0.45 * ratio
    else:
        base = 0.25 + 0.35 * ratio
    if validation_issues:
        base *= 0.85
    return max(0.0, min(1.0, round(base, 4)))
