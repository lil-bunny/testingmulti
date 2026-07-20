"""
POD PDF → per-page vision extraction and reconciliation.

Flow: rasterize (or staged images) → parallel ``achat_vision_json`` under
``POD_PAGE_CONCURRENCY`` → rule-based reconcile. Broker context is rendered into
Hub/JSON prompts once via ``resolve_pod_vision_prompts``, then reused per page.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING

from openai import AsyncOpenAI

from app.core.config import settings
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_pod_vision_prompts
from app.tools.llm_client import LLMClientError, achat_vision_json, build_async_llm_client
from app.tools.pdf_to_images import (
    PdfRasterOptions,
    PodPdfTooLargeError,
    rasterize_pdf_to_jpeg_paths,
)

if TYPE_CHECKING:
    from app.integrations.langsmith import RenderedPrompt

logger = logging.getLogger(__name__)


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
            error_page.get("error_category", "unknown")
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
    dpi: int = 150,
    max_side_px: int = 0,
    jpeg_quality: int = 85,
    thread_count: int = 1,
    max_pages: int | None = None,
) -> list[str]:
    """Rasterize PDF to JPEGs under ``temp_dir`` via shared ``pdf_to_images``."""
    _ = thread_count  # pdf_to_images always uses thread_count=1 for page renders
    return rasterize_pdf_to_jpeg_paths(
        pdf_path,
        temp_dir,
        PdfRasterOptions(
            dpi=dpi,
            max_side_px=max_side_px,
            jpeg_quality=jpeg_quality,
            max_pages=max_pages,
        ),
    )


async def analyze_page_async(
    image_path: str,
    page_number: int,
    *,
    vision_prompts: RenderedPrompt,
    prompt_trace: PromptTraceMetadata | None = None,
    max_tokens: int | None = None,
    temperature: float = 0.0,
    client: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    """Per-page vision extraction; pass ``client`` when fanning out in one event loop"""
    load_id = Path(image_path).stem
    system_prompt = vision_prompts.system
    user_prompt = vision_prompts.user or " "

    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        extracted_data = await achat_vision_json(
            system_prompt,
            user_prompt,
            image_data,
            temperature=temperature,
            max_tokens=max_tokens,
            prompt_trace=prompt_trace,
            client=client,
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


async def _analyze_pages_async(
    image_paths: list[str],
    *,
    vision_prompts: RenderedPrompt,
    prompt_trace: PromptTraceMetadata | None,
    max_tokens: int | None,
    load_id: str,
) -> list[dict[str, Any]]:
    """Run page vision in parallel under ``POD_PAGE_CONCURRENCY``.

    Shares one ``AsyncOpenAI`` client; semaphore caps in-flight pages.
    Returns one result dict per image (extraction or error), unordered until caller sorts.
    """
    concurrency = max(1, min(settings.POD_PAGE_CONCURRENCY, len(image_paths)))
    logger.info(
        "pod_extraction: parallel page vision load_id=%s page_count=%s concurrency=%s",
        load_id,
        len(image_paths),
        concurrency,
    )

    async with build_async_llm_client(
        max_connections=concurrency,
    ) as client:
        sem = asyncio.Semaphore(concurrency)

        async def _one(i: int, img_path: str) -> dict[str, Any]:
            page_num = i + 1
            async with sem:
                result = await analyze_page_async(
                    img_path,
                    page_num,
                    vision_prompts=vision_prompts,
                    prompt_trace=prompt_trace,
                    max_tokens=max_tokens,
                    temperature=0.0,
                    client=client,
                )
            row = {
                **result,
                "timestamp": datetime.now().isoformat(),
            }
            if "load_id" not in row:
                row["load_id"] = load_id
            return row

        return list(await asyncio.gather(*(_one(i, p) for i, p in enumerate(image_paths))))


def extract_from_pdf_path(
    pdf_path: str,
    *,
    broker_name: str | None = None,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
    fast_mode: bool = False,
    max_pages: int | None = None,
    prepared_image_paths: list[str] | None = None,
) -> tuple[list[Any], dict[str, Any], list[str], dict[str, Any]]:
    """
    Sync pipeline: rasterize (or staged images) → parallel per-page vision → reconcile.

    When ``prepared_image_paths`` are present and readable, skip PDF rasterization and
    analyze those JPEGs/PNGs directly (worker-local staged validated images).

    Page vision runs inside ``asyncio.run`` with ``POD_PAGE_CONCURRENCY`` cap.
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

        # Prefer worker-staged JPEGs when every prepared path is readable.
        staged = [
            str(p).strip()
            for p in (prepared_image_paths or [])
            if str(p).strip() and os.path.isfile(str(p).strip())
        ]
        if staged and len(staged) == len(
            [str(p).strip() for p in (prepared_image_paths or []) if str(p).strip()]
        ):
            image_paths = staged
            if max_pages and max_pages > 0:
                image_paths = image_paths[:max_pages]
            logger.info(
                "pod_extraction: using staged vision images load_id=%s page_count=%s",
                load_id,
                len(image_paths),
            )
        else:
            # Rasterize PDF pages into work_dir when staged images are incomplete.
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
                logger.exception(
                    "pod_extraction: critical PDF processing failure load_id=%s",
                    load_id,
                )
                sorted_results = [
                    {
                        "page_number": 1,
                        "timestamp": datetime.now().isoformat(),
                        "error": error_msg,
                        "error_type": type(e).__name__,
                        "load_id": load_id,
                    }
                ]
                final_pod_data, reconciliation_log = reconcile_pod_data(
                    sorted_results, broker_name
                )
                validation_issues = validate_pod_consistency(final_pod_data)
                return (
                    sorted_results,
                    final_pod_data,
                    validation_issues,
                    reconciliation_log,
                )

        logger.info(
            "pod_extraction: processing PDF pages load_id=%s page_count=%s",
            load_id,
            len(image_paths),
        )

        # Parallel page vision, then reconcile across pages (broker filter on carrier).
        processed_results = asyncio.run(
            _analyze_pages_async(
                image_paths,
                vision_prompts=vision_prompts,
                prompt_trace=prompt_trace,
                max_tokens=max_tokens,
                load_id=load_id,
            )
        )

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
