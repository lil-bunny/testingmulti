"""
Rate confirmation PDF → per-page vision extraction.

Uses ``app.tools.llm_client.chat_vision_json`` (same LLM_* settings as text JSON calls).
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.prompt_step_keys import RATECON_PAGE_EXTRACTION
from app.domain.vision_prompt_templates import (
    RATECON_PAGE_SYSTEM,
    RATECON_PAGE_USER,
)
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_ratecon_vision_prompts
from app.tools.llm_client import LLMClientError, chat_vision_json
from app.tools.pdf_raster import (
    PdfRasterOptions,
    PdfTooLargeError,
    make_temp_workdir,
    rasterize_pdf_to_jpeg_paths,
)

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = RATECON_PAGE_SYSTEM
USER_PROMPT = RATECON_PAGE_USER


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


def extract_from_pdf_path(
    pdf_path: str,
    *,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
    stage_dir: str | Path | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """
    Render each PDF page to JPEG, run vision JSON extraction per page, merge fields.

    Page JPEGs land under ``stage_dir`` when provided (FreightX ratecon staging);
    otherwise under ``RATECON_STAGE_ROOT``. Returns ``(page_results, merged_extracted_data)``.
    """
    del model_label  # reserved for callers / future tracing
    vision_prompts, prompt_metadata = resolve_ratecon_vision_prompts(tenant_settings)
    prompt_trace = PromptTraceMetadata.from_load(
        RATECON_PAGE_EXTRACTION,
        prompt_metadata,
    )

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

        final_data: dict[str, Any] = {
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

        if final_data.get("shipment_identifiers") and not final_data.get(
            "primary_identifier"
        ):
            final_data["primary_identifier"] = final_data["shipment_identifiers"][0]
        if not final_data.get("po_number") and final_data.get("primary_identifier"):
            final_data["po_number"] = final_data.get("primary_identifier")

        return page_results, final_data
    except PdfTooLargeError:
        raise
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
