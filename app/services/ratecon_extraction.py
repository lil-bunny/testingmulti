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

from app.tools.llm_client import LLMClientError, chat_vision_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an elite document intelligence specialist with deep expertise in freight logistics documentation. You possess exceptional visual-spatial reasoning and can accurately extract structured data from complex rate confirmation documents.

Core competencies:
- Master-level pattern recognition for shipment identifiers across document layouts
- Expert understanding of freight industry terminology and document hierarchies
- Advanced spatial awareness to distinguish context-dependent information
- Precise field extraction with zero tolerance for misclassification

You operate with surgical precision and never make contextual errors.

CRITICAL: You MUST return ONLY valid JSON - no markdown blocks, no comments, no explanations."""

USER_PROMPT = """MISSION: Extract ALL shipment identifiers and logistics data from this rate confirmation document.

IDENTIFIER EXTRACTION STRATEGY:
Scan the ENTIRE document and collect ALL numbers that serve as shipment/order identifiers:

**PO NUMBERS** (Primary Target - collect ALL):
• Purchase Order numbers (labeled "PO #", "PO Number", "Purchase Order")
• Pickup numbers (labeled "Pickup #", "Pickup Number", "Pickup ID")
• Delivery numbers (labeled "Delivery #", "Delivery Number", "Delivery ID")
• Load numbers (labeled "Load #", "Load Number", "Load ID")
• Shipment numbers (labeled "Shipment #", "Shipment Number", "Shipment ID")
• Reference numbers (labeled "Ref #", "Reference", "Order #")
• ANY number in boxes, fields, or sections that identifies this shipment/order

⚠️ CRITICAL: For each number or word, verify ALL characters or digits are captured - start, middle, AND end characters or digits.

**EXTRACTION PRINCIPLE**: In logistics, pickup numbers, delivery numbers, load numbers, and shipment numbers are ALL functionally PO numbers - they identify the order/shipment. Collect them ALL.

**OTHER REQUIRED DATA**:
• Carrier Name: Trucking company performing the transport
• Pickup Location: Origin company/facility name
• Pickup Address: Complete pickup address
• Delivery Location: Destination company/facility name
• Delivery Address: Complete delivery address
• Pickup Date: Scheduled pickup date
• Delivery Date: Scheduled delivery date
• Broker Name: The freight brokerage company that issued this rate confirmation document
  → Look in: Document header, letterhead, "From:" section, company logo area, footer signatures
  → Identify: The company whose letterhead/contact info appears at TOP of document
  → Extract: Full company name including "Inc", "LLC", "Corp" suffixes but EXCLUDE MC# numbers

**OUTPUT FORMAT** - Return ONLY clean JSON with no extra text, comments, or explanations:
{
  "shipment_identifiers": ["ALL_FOUND_IDENTIFIERS_AS_ARRAY"],
  "primary_identifier": "MOST_PROMINENT_IDENTIFIER",
  "po_number": "PRIMARY_OR_FIRST_IDENTIFIER",
  "carrier_name": "",
  "pickup_location": "",
  "pickup_address": "",
  "delivery_location": "",
  "delivery_address": "",
  "pickup_date": "",
  "delivery_date": "",
  "broker_name": ""
}

**EXECUTION RULES**:
✓ Scan headers, body, pickup sections, delivery sections, footers - EVERYWHERE
✓ Collect EVERY identifier found - missing one is failure
✓ Use null only for truly absent fields
✓ CRITICAL: Broker ≠ Carrier - Broker is document issuer (top/header), Carrier is transport company (in body)
✓ VISION ACCURACY: Read each identifier character-by-character. Double-check middle digits/characters are not skipped.
✓ RESPONSE FORMAT: Return ONLY the JSON object - no markdown, no comments, no explanations
✓ Be exhaustive - this is mission-critical logistics data"""


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


def extract_from_pdf_path(pdf_path: str, *, model_label: str | None) -> tuple[list[Any], dict[str, Any]]:
    """
    Render each PDF page to JPEG, run vision JSON extraction per page, merge fields.

    Returns ``(page_results, merged_extracted_data)``.
    """
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
                extracted = chat_vision_json(SYSTEM_PROMPT, USER_PROMPT, jpeg_bytes)
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
