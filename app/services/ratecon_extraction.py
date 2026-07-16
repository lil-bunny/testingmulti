"""
Ratecon PDF → structured field extraction.

Prefer native/OCR text into a text LLM (cheaper). Fall back to per-page vision
when text is empty, sparse, or missing critical shipment fields.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.prompt_step_keys import RATECON_PAGE_EXTRACTION
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_ratecon_vision_prompts
from app.tools.llm_client import LLMClientError, chat_json, chat_vision_json
from app.tools.pdf_page_text_extractor import PdfPageTextExtractor
from app.tools.pdf_to_images import (
    PdfRasterOptions,
    PdfTooLargeError,
    make_temp_workdir,
    rasterize_pdf_to_jpeg_paths,
)

logger = logging.getLogger(__name__)


def _merge_extracted_data(
    current_data: dict[str, Any], new_data: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(current_data)
    if new_data.get("shipment_identifiers"):
        if not merged.get("shipment_identifiers"):
            merged["shipment_identifiers"] = []
        for identifier in new_data["shipment_identifiers"]:
            if identifier and identifier not in merged["shipment_identifiers"]:
                merged["shipment_identifiers"].append(identifier)
    for key, value in new_data.items():
        if key == "shipment_identifiers":
            continue
        if not merged.get(key) and value and str(value).strip().lower() not in ("", "null"):
            merged[key] = value
    return merged


def _empty_extracted() -> dict[str, Any]:
    return {
        "shipment_identifiers": [],
        "primary_identifier": None,
        "po_number": None,
        "carrier_name": None,
        "pickup_location": None,
        "pickup_address": None,
        "delivery_location": None,
        "delivery_address": None,
        "pickup_date": None,
        "delivery_date": None,
        "broker_name": None,
    }


def _finalize_identifiers(final_data: dict[str, Any]) -> dict[str, Any]:
    if final_data.get("shipment_identifiers") and not final_data.get("primary_identifier"):
        final_data["primary_identifier"] = final_data["shipment_identifiers"][0]
    if not final_data.get("po_number") and final_data.get("primary_identifier"):
        final_data["po_number"] = final_data.get("primary_identifier")
    return final_data


def _has_critical_fields(data: dict[str, Any]) -> bool:
    ids = data.get("shipment_identifiers") or []
    if ids:
        return True
    if data.get("primary_identifier") or data.get("po_number"):
        return True
    filled = sum(
        1
        for key in ("carrier_name", "pickup_location", "delivery_location", "broker_name")
        if data.get(key)
    )
    return filled >= 2


def _text_user_prompt(base_user: str, document_text: str) -> str:
    body = (document_text or "").strip()
    if len(body) > 60_000:
        body = body[:60_000] + "\n\n[truncated]"
    return (
        f"{base_user.strip()}\n\n"
        "DOCUMENT TEXT (extracted from the rate confirmation PDF; "
        "use this text instead of an image):\n"
        f"{body}"
    )


def _extract_via_text(
    pdf_bytes: bytes,
    *,
    vision_prompts: Any,
    prompt_trace: PromptTraceMetadata,
    doc_label: str,
) -> tuple[list[Any], dict[str, Any]] | None:
    """
    Ratecon text path: ``PdfPageTextExtractor`` → ``chat_json``.

    Returns ``None`` to signal vision fallback (no usable text, LLM failure, or
    missing critical fields).
    """
    pdf_page_text_extractor = PdfPageTextExtractor()
    document_text = pdf_page_text_extractor.extract_full_text(
        pdf_bytes,
        prefer_native=True,
        ocr_if_sparse=True,
        doc_label=doc_label,
    )
    if not (document_text or "").strip():
        logger.info("ratecon_extraction: no text extracted; falling back to vision")
        return None

    user_prompt = _text_user_prompt(vision_prompts.user or "", document_text)
    try:
        extracted = chat_json(
            vision_prompts.system,
            user_prompt,
            temperature=0.0,
            prompt_trace=prompt_trace,
            tags=["ratecon_text_extraction"],
        )
    except LLMClientError:
        logger.exception("ratecon_extraction: text LLM failed; falling back to vision")
        return None
    except Exception:
        logger.exception("ratecon_extraction: text path error; falling back to vision")
        return None

    if not isinstance(extracted, dict):
        return None

    final_data = _finalize_identifiers(_merge_extracted_data(_empty_extracted(), extracted))
    if not _has_critical_fields(final_data):
        logger.info(
            "ratecon_extraction: text path missing critical fields; falling back to vision"
        )
        return None

    page_results = [
        {
            "page_number": 1,
            "extracted_data": extracted,
            "extraction_mode": "text",
            "timestamp": datetime.now().isoformat(),
        }
    ]
    return page_results, final_data


def _extract_via_vision(
    pdf_path: str,
    *,
    vision_prompts: Any,
    prompt_trace: PromptTraceMetadata,
    stage_dir: str | Path | None,
) -> tuple[list[Any], dict[str, Any]]:
    """Ratecon vision fallback: rasterize pages and run ``chat_vision_json`` per page."""
    parent = Path(stage_dir) if stage_dir else Path(settings.RATECON_STAGE_ROOT)
    work_dir = make_temp_workdir(prefix="ratecon_pages", directory=parent)
    try:
        image_paths = rasterize_pdf_to_jpeg_paths(
            pdf_path,
            work_dir,
            PdfRasterOptions(
                dpi=settings.POD_IMAGE_DPI,
                max_side_px=settings.POD_IMAGE_MAX_SIDE_PX,
                jpeg_quality=settings.POD_JPEG_QUALITY,
            ),
        )
        if not image_paths:
            return (
                [
                    {
                        "page_number": 1,
                        "error": "no_pages_from_pdf",
                        "timestamp": datetime.now().isoformat(),
                    }
                ],
                {},
            )

        final_data = _empty_extracted()
        page_results: list[Any] = []

        for i, img_path in enumerate(image_paths):
            page_num = i + 1
            with open(img_path, "rb") as f:
                jpeg_bytes = f.read()
            try:
                extracted = chat_vision_json(
                    vision_prompts.system,
                    vision_prompts.user,
                    jpeg_bytes,
                    prompt_trace=prompt_trace,
                )
                page_results.append(
                    {
                        "page_number": page_num,
                        "extracted_data": extracted,
                        "extraction_mode": "vision",
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                final_data = _merge_extracted_data(final_data, extracted)
            except LLMClientError as exc:
                page_results.append(
                    {
                        "page_number": page_num,
                        "error": str(exc),
                        "timestamp": datetime.now().isoformat(),
                    }
                )
            except Exception as exc:
                logger.exception("ratecon_extraction: page %s failed", page_num)
                page_results.append(
                    {
                        "page_number": page_num,
                        "error": str(exc),
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return page_results, _finalize_identifiers(final_data)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def extract_from_pdf_path(
    pdf_path: str,
    *,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
    stage_dir: str | Path | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Extract Ratecon fields from a PDF path.

    Tries text first (native + sparse OCR); otherwise per-page vision. Vision
    JPEGs are written under ``stage_dir`` when provided.
    Returns ``(page_results, merged_extracted_data)``.
    """
    del model_label  # reserved for callers / future tracing
    vision_prompts, prompt_metadata = resolve_ratecon_vision_prompts(tenant_settings)
    prompt_trace = PromptTraceMetadata.from_load(
        RATECON_PAGE_EXTRACTION,
        prompt_metadata,
    )

    try:
        with open(pdf_path, "rb") as fh:
            pdf_bytes = fh.read()
    except OSError:
        logger.exception("ratecon_extraction: failed to read pdf_path=%s", pdf_path)
        return (
            [
                {
                    "page_number": 1,
                    "error": "pdf_read_failed",
                    "timestamp": datetime.now().isoformat(),
                }
            ],
            {},
        )

    doc_label = Path(pdf_path).stem[:80] or "ratecon"
    try:
        text_result = _extract_via_text(
            pdf_bytes,
            vision_prompts=vision_prompts,
            prompt_trace=prompt_trace,
            doc_label=doc_label,
        )
        if text_result is not None:
            logger.info(
                "ratecon_extraction: used text path pdf=%s",
                doc_label,
            )
            return text_result

        return _extract_via_vision(
            pdf_path,
            vision_prompts=vision_prompts,
            prompt_trace=prompt_trace,
            stage_dir=stage_dir,
        )
    except PdfTooLargeError:
        raise
