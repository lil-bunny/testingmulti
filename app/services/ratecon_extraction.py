"""
Rate confirmation PDF → per-page vision extraction.

Uses ``app.tools.llm_client.chat_vision_json`` (same LLM_* settings as text JSON calls).
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
from datetime import datetime
from typing import Any

from pdf2image import convert_from_path

from app.domain.prompt_step_keys import RATECON_PAGE_EXTRACTION
from app.domain.vision_prompt_templates import (
    RATECON_PAGE_SYSTEM,
    RATECON_PAGE_USER,
)
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_ratecon_vision_prompts
from app.tools.llm_client import LLMClientError, chat_vision_json

logger = logging.getLogger(__name__)

# Legacy aliases for tests and direct imports.
SYSTEM_PROMPT = RATECON_PAGE_SYSTEM
USER_PROMPT = RATECON_PAGE_USER


def _has_all_required_fields(extracted_data: dict[str, Any]) -> bool:
    has_identifiers = (
        extracted_data.get("shipment_identifiers")
        and len(extracted_data.get("shipment_identifiers", [])) > 0
    ) or extracted_data.get("primary_identifier")
    required_fields = [
        "carrier_name",
        "pickup_location",
        "delivery_location",
        "pickup_date",
        "delivery_date",
    ]
    missing: list[str] = []
    if not has_identifiers:
        missing.append("shipment_identifiers")
    missing.extend(
        f for f in required_fields if not extracted_data.get(f)
    )
    return len(missing) == 0


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
) -> tuple[list[Any], dict[str, Any]]:
    """
    Render each PDF page to JPEG, run vision JSON extraction per page, merge fields.

    Returns ``(page_results, merged_extracted_data)``.
    """
    vision_prompts, prompt_metadata = resolve_ratecon_vision_prompts(tenant_settings)
    prompt_trace = PromptTraceMetadata.from_load(
        RATECON_PAGE_EXTRACTION,
        prompt_metadata,
    )

    work_dir = tempfile.mkdtemp(prefix="ratecon_extract_")
    try:
        images = convert_from_path(pdf_path, fmt="jpeg")
        if not images:
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

        for i, image in enumerate(images):
            page_num = i + 1
            img_path = os.path.join(work_dir, f"page_{page_num:03d}.jpg")
            image.save(img_path, "JPEG", quality=85, optimize=True)
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
                if _has_all_required_fields(final_data):
                    logger.info(
                        "ratecon_extraction: required fields satisfied mid-document page=%s",
                        page_num,
                    )
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

        logger.info(
            "ratecon_extraction: pages=%s identifiers=%s model=%s",
            len(images),
            len(final_data.get("shipment_identifiers") or []),
            model_label,
        )
        return page_results, final_data
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
