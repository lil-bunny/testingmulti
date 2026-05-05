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

from app.tools.llm_client import LLMClientError, chat_vision_json

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = None


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


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


def get_prompt(broker_name=None):
    """
    Returns the prompt for the LLM.

    NOTE: pickup_location is NOT passed to the prompt to ensure unbiased extraction.
    The POD pickup_location should be extracted independently from the document,
    then compared with RateCon pickup_location during validation.
    """
    broker_context = ""
    if broker_name:
        broker_context = f"\n\n🚨 CRITICAL RULE: The broker for this shipment is '{broker_name}'. This is the freight broker who arranged the shipment, NOT the carrier company. \n\n❌ NEVER extract '{broker_name}' or similar variations as the 'carrier_name'. \n\n✅ The carrier is the actual trucking company or cargo company that physically transported the goods. If you cannot find a different carrier name than '{broker_name}', then DO NOT extract any carrier information. and mark it as null"

    return f"""
Analyze this document page, which is part of a Proof of Delivery (POD) packet.
Extract logistical information and evidence of receipt with high precision.{broker_context}

Return ONLY a single JSON object with the following structure:
{{
  "page_type": "...",
  "fields": [
    {{
      "key": "...",
      "value": "...",
      "confidence": ...,
      "context_snippet": "..."
    }}
  ],
  "proof_of_receipt": {{
    "has_receiver_signature": true/false,
    "receiver_signature_location": "...",
    "has_stamp": true/false,
    "delivery_confirmation_reasoning": "..."
  }},
  "stop_times": [
    {{ "pickup_checkin_time": "", "pickup_checkout_time": "", "delivery_checkin_time": "", "delivery_checkout_time": "" }}
  ]
}}

SCHEMA and INSTRUCTIONS:
CRITICAL RULE: If you cannot find a specific piece of information with high confidence, DO NOT GUESS. Omit that field from the "fields" array. It is better to have a missing field than an incorrect one.

--- LOCATION & ADDRESS RULES (VERY IMPORTANT) ---
1.  The `pickup_location` and `pickup_address` MUST come from the section explicitly labeled 'Shipper', 'From', 'Origin', or 'Ship Site'.
2.  The `destination_location` and `destination_address` MUST come from the section explicitly labeled 'Consignee', 'To', 'Destination', or 'Ship To'.
3.  NEVER mix information between these sections. An address found under the 'Shipper' block cannot be the `destination_address`.
4.  Pay close attention to the visual layout to correctly associate a location name with its corresponding address.

--- GENERAL FIELDS ---
1.  "page_type": Classify the page. Must be one of: "BILL_OF_LADING", "LUMPER_RECEIPT", "ITEMIZED_LIST", "UNKNOWN".
2.  "fields": An array of extracted data.
    - "key": Must be one of: "carrier_name", "po_number", "pickup_location", "pickup_address", "destination_location", "destination_address", "stamp_company_name".
    - "value": The extracted value as a string.
    - "confidence": Your confidence (1-100).
    - "context_snippet": A small text snippet showing the value's context.
3.  "proof_of_receipt": An object for delivery evidence.
    - "has_receiver_signature": CRITICAL - Set to true if there is a signature in the CONSIGNEE/RECEIVER section OR a printed name in a 'Receiver' or 'RECVR' field on a warehouse receipt. Do NOT count signatures in the carrier or driver boxes.
    - "receiver_signature_location": If a signature is found, specify location: "Consignee Box", "On Stamp", "Receiver Field", "Handwritten Note", "N/A".
    - "has_stamp": true if a company ink stamp is visible, otherwise false.
    - "delivery_confirmation_reasoning": Provide a brief, specific explanation of what evidence you found (or didn't find) for delivery confirmation. Examples: "Receiver signature visible in consignee box", "Company stamp present with date", "No signature or stamp evidence found", "Handwritten receiver name in delivery field".

--- FIELD-SPECIFIC RULES ---
- "carrier_name": The actual trucking company or cargo company that physically transported the goods (e.g., 'Bajwa Truckers'). Look for this on 'LUMPER_RECEIPT' or 'BILL_OF_LADING' or next to 'Warehouse Carrier'. Make sure to identify if there are any updations or changes made to the existing carrier name and catch them precisely. If you cannot find a different carrier name than '{broker_name}', then DO NOT extract any carrier information. and mark it as null
- "po_number": Scan the entire page for all possible PO(Purchase Order) numbers and Delivery numbers precisely without missing out on any possible PO or Delivery numbers. Extract ONLY the clean numeric/alphanumeric identifiers from the document and do not pick up any other words or text. READ CAREFULLY AND ACCURATELY - do not miss any middle characters or digits when extracting these numbers.

--- STOP TIMES (CHECK-IN / CHECK-OUT) ---
4.  "stop_times": REQUIRED. You MUST always include a "stop_times" array in your response. Look for any of: check-in time, check-out time, arrival time, departure time, gate in, gate out, appointment time, scheduled time, actual time, in/out times, or similar time blocks on the page (common on warehouse receipts, dock receipts, BOLs with time blocks, delivery tickets).
    - For each logical stop (pickup and/or delivery) on the page, add one object with: "pickup_checkin_time", "pickup_checkout_time", "delivery_checkin_time", "delivery_checkout_time". Use empty string "" for any time not found or not applicable for that stop.
    - pickup_checkin_time / pickup_checkout_time: use for origin/shipper/pickup stop arrival and departure.
    - delivery_checkin_time / delivery_checkout_time: use for destination/consignee/delivery stop arrival and departure.
    - TIMESTAMP FORMAT: Every non-empty time value MUST be ISO 8601 UTC: "YYYY-MM-DDTHH:mm:ssZ" (e.g. "2026-02-06T07:34:49Z"). Convert document times (e.g. "02/06/26 7:34 AM", "Jan 15 08:00", "7:34 AM") to this format. If timezone is given, convert to UTC and append Z. If no times are found on the page, return one object with all four keys set to "".
    - Example (one pickup + one delivery): [{{"pickup_checkin_time":"2026-02-06T07:34:49Z","pickup_checkout_time":"2026-02-06T09:30:00Z","delivery_checkin_time":"","delivery_checkout_time":""}}, {{"pickup_checkin_time":"","pickup_checkout_time":"","delivery_checkin_time":"2026-02-07T14:00:00Z","delivery_checkout_time":"2026-02-07T14:45:00Z"}}]
    - Example (no times on page): [{{"pickup_checkin_time":"","pickup_checkout_time":"","delivery_checkin_time":"","delivery_checkout_time":""}}]
"""


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
    thread_count: int = 2,
    max_pages: int | None = None,
) -> list[str]:
    """
    Rasterize PDF to JPEGs under ``temp_dir``, or treat ``pdf_path`` as a single image.

    Same responsibilities as before; **synchronous** like ``ratecon_extraction``.
    """
    load_id = Path(pdf_path).stem.replace(" POD", "").replace("_", "")

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
                prepared_image = image.convert("RGB")
                prepared_image = _resize_for_vision(prepared_image, max_side_px=max_side_px)
                image_path = os.path.join(temp_dir, "page_001.jpg")
                prepared_image.save(
                    image_path,
                    "JPEG",
                    quality=max(25, min(95, int(jpeg_quality))),
                    optimize=True,
                    progressive=True,
                )
                logger.info(
                    "pod_extraction: image attachment prepared load_id=%s path=%s",
                    load_id,
                    image_path,
                )
                return [image_path]
        except (UnidentifiedImageError, OSError, ValueError):
            pass

        images = convert_from_path(
            pdf_path,
            fmt="jpeg",
            dpi=dpi,
            thread_count=thread_count,
            first_page=1,
            last_page=max_pages if max_pages and max_pages > 0 else None,
        )
        if not images:
            raise ValueError(f"No images could be extracted from PDF: {pdf_path}")

        image_paths = [os.path.join(temp_dir, f"page_{i+1:03d}.jpg") for i in range(len(images))]
        for i, image in enumerate(images):
            image = _resize_for_vision(image, max_side_px=max_side_px)
            image.save(
                image_paths[i],
                "JPEG",
                quality=max(25, min(95, int(jpeg_quality))),
                optimize=True,
                progressive=True,
            )

        logger.info(
            "pod_extraction: PDF conversion successful load_id=%s page_count=%s",
            load_id,
            len(images),
        )
        return image_paths
    except Exception as e:
        error_msg = f"Failed to convert PDF to images: {type(e).__name__}: {str(e)}"
        logger.exception("pod_extraction: PDF conversion failed pdf_path=%s", pdf_path)
        raise Exception(error_msg) from e


def analyze_page(
    image_path: str,
    page_number: int,
    broker_name=None,
    *,
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Per-page vision extraction (sync ``chat_vision_json``, same pattern as ratecon)."""
    load_id = Path(image_path).stem
    prompt_text = get_prompt(broker_name)

    try:
        with open(image_path, "rb") as f:
            image_data = f.read()
        extracted_data = chat_vision_json(
            prompt_text,
            " ",
            image_data,
            timeout_s=300.0,
            temperature=temperature,
            max_tokens=max_tokens,
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

    work_dir = tempfile.mkdtemp(prefix="pod_extraction_")
    try:
        default_dpi = _env_int("POD_IMAGE_DPI", 200)
        default_quality = _env_int("POD_JPEG_QUALITY", 85)
        default_max_side = _env_int("POD_IMAGE_MAX_SIDE_PX", 0)
        default_threads = _env_int("POD_PDF_THREAD_COUNT", 2)

        if fast_mode:
            dpi = _env_int("POD_FAST_IMAGE_DPI", 130)
            jpeg_quality = _env_int("POD_FAST_JPEG_QUALITY", 70)
            max_side_px = _env_int("POD_FAST_IMAGE_MAX_SIDE_PX", 1600)
            thread_count = _env_int("POD_FAST_PDF_THREAD_COUNT", 4)
            max_tokens = _env_int("POD_FAST_MAX_TOKENS", 700)
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
