"""
POD vs Rate Confirmation cross-validation (rule engine + optional LLM semantic checks).

Ported from ``old/agents/pod_validator/pod_validation.py`` and
``old/services/pod_validation_service.py`` (business rules preserved).
Uses ``chat_json`` with app ``LLM_*`` settings; fuzzy matching via ``thefuzz``.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from thefuzz import fuzz

from app.tools.llm_client import LLMClientError, chat_json

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """A generic text normalizer."""
    if not isinstance(text, str):
        return ""
    text = text.lower()
    for suffix in [" inc", " llc", " inc.", " llc."]:
        text = text.replace(suffix, "")
    return text.strip().replace(",", "")


def normalize_address(address: str) -> str:
    """Simple address normalization."""
    if not isinstance(address, str):
        return ""
    return address.lower().replace(" st", " street").replace(" ave", " avenue").replace(" s ", " south ")


def ask_llm_for_semantic_match(field_type: str, value1: str, value2: str) -> tuple[bool, str]:
    """
    Asks an LLM if two strings are semantically equivalent from a logistics auditing perspective.
    """
    system_prompt = """You are a logistics data auditor. Your task is to determine if a value from a Proof of Delivery (POD) matches the corresponding value on a Rate Confirmation (Rate Con), even if the names are different.

Consider corporate relationships (e.g., a parent company on the Rate Con and a specific store brand on the POD), common abbreviations, and other real-world variations.

Answer ONLY with a single JSON object with the keys "match" (boolean) and "reason" (a brief explanation)."""

    user_prompt = f"""Field being compared: '{field_type}'
Rate Confirmation Value: "{value2}"
Proof of Delivery Value: "{value1}"

Do these represent a valid match for auditing purposes?"""

    try:
        llm_response = chat_json(
            system_prompt,
            user_prompt,
            temperature=0.1,
            timeout_s=120.0,
        )
        return bool(llm_response.get("match")), str(
            llm_response.get("reason", "No reason provided.")
        )
    except LLMClientError as exc:
        logger.warning("pod_vs_ratecon: semantic match LLM failed field=%s err=%s", field_type, exc)
        return False, f"LLM call failed: {exc}"
    except Exception as exc:
        logger.exception("pod_vs_ratecon: semantic match unexpected error field=%s", field_type)
        return False, f"LLM call failed: {exc}"


def validate_pod_against_ratecon(pod_data: dict, ratecon_data: dict) -> dict[str, Any]:
    """
    Compares reconciled POD data against Rate Confirmation data using the hybrid approach.
    """
    validation_report: dict[str, Any] = {
        "overall_status": "PASS",
        "field_validations": [],
    }

    comparisons = [
        {"key": "po_number", "rc_key": "po_number", "type": "po_number"},
        {"key": "carrier_name", "rc_key": "carrier_name", "type": "fuzzy"},
        {"key": "pickup_location", "rc_key": "pickup_location", "type": "fuzzy"},
        {"key": "pickup_address", "rc_key": "pickup_address", "type": "address"},
        {"key": "destination_location", "rc_key": "delivery_location", "type": "fuzzy"},
        {"key": "destination_address", "rc_key": "delivery_address", "type": "address"},
    ]

    for comp in comparisons:
        pod_key, rc_key = comp["key"], comp["rc_key"]
        pod_val, rc_val = pod_data.get(pod_key), ratecon_data.get(rc_key)

        if pod_val is None:
            if pod_key == "carrier_name":
                validation_report["field_validations"].append(
                    {
                        "field": pod_key,
                        "status": "PASS",
                        "pod_value": "Missing",
                        "rate_con_value": str(rc_val),
                        "notes": "PASS per business rule: Carrier name can be missing on POD.",
                    }
                )
                continue
            if pod_key == "po_number":
                rc_has_identifiers = (
                    (
                        ratecon_data.get("shipment_identifiers")
                        and len(ratecon_data["shipment_identifiers"]) > 0
                    )
                    or ratecon_data.get("primary_identifier")
                    or rc_val
                )

                all_rc_identifiers = []
                if ratecon_data.get("shipment_identifiers"):
                    all_rc_identifiers.extend(ratecon_data["shipment_identifiers"])
                elif rc_val:
                    all_rc_identifiers.append(str(rc_val))

                validation_report["field_validations"].append(
                    {
                        "field": pod_key,
                        "status": "FAIL" if rc_has_identifiers else "PASS",
                        "pod_value": "Missing",
                        "rate_con_value": ", ".join(all_rc_identifiers)
                        if all_rc_identifiers
                        else "Missing",
                        "notes": "Identifier missing from POD"
                        if rc_has_identifiers
                        else "Identifier missing from both POD and Rate Confirmation",
                    }
                )
                continue
            continue

        if rc_val is None:
            if pod_key == "po_number":
                rc_has_identifiers = (
                    ratecon_data.get("shipment_identifiers")
                    and len(ratecon_data["shipment_identifiers"]) > 0
                ) or ratecon_data.get("primary_identifier")

                if rc_has_identifiers:
                    rc_val = "see_shipment_identifiers"
                else:
                    validation_report["field_validations"].append(
                        {
                            "field": pod_key,
                            "status": "FAIL",
                            "pod_value": str(pod_val),
                            "rate_con_value": "Missing",
                            "notes": "Identifier missing from Rate Confirmation",
                        }
                    )
                    continue
            else:
                continue

        result = {
            "field": pod_key,
            "status": "FAIL",
            "pod_value": str(pod_val),
            "rate_con_value": str(rc_val),
        }
        match = False

        if comp["type"] == "exact":
            match = normalize_text(pod_val) == normalize_text(rc_val)
            result["notes"] = "Exact match."
        elif comp["type"] == "po_number":

            def normalize_po_identifier(po):
                if po is None:
                    return ""
                po_str = str(po).strip()
                po_str = re.sub(
                    r"^(po#?\s*|p0\s*|purchase\s*order\s*[#:]?\s*)",
                    "",
                    po_str,
                    flags=re.IGNORECASE,
                )
                po_str = re.sub(r"[^\w]", "", po_str)
                normalized = po_str.lstrip("0") or "0"
                return normalized.upper()

            pod_pos = [normalize_po_identifier(po) for po in str(pod_val).split(",")]
            original_pod_pos = [po.strip() for po in str(pod_val).split(",")]

            rc_identifiers = []
            original_rc_identifiers = []

            if "shipment_identifiers" in ratecon_data and ratecon_data["shipment_identifiers"]:
                rc_identifiers.extend([str(x) for x in ratecon_data["shipment_identifiers"]])
                original_rc_identifiers.extend([str(x) for x in ratecon_data["shipment_identifiers"]])

            if "primary_identifier" in ratecon_data and ratecon_data["primary_identifier"]:
                primary_str = str(ratecon_data["primary_identifier"])
                if primary_str not in rc_identifiers:
                    rc_identifiers.append(primary_str)
                    original_rc_identifiers.append(primary_str)

            if not rc_identifiers and rc_val:
                rc_identifiers.extend(str(rc_val).split(","))
                original_rc_identifiers.extend([po.strip() for po in str(rc_val).split(",")])

            rc_pos = [normalize_po_identifier(identifier) for identifier in rc_identifiers]

            common_pos = set(pod_pos) & set(rc_pos)
            match = len(common_pos) > 0

            if match:
                matched_pairs = []
                for i, norm_pod in enumerate(pod_pos):
                    for j, norm_rc in enumerate(rc_pos):
                        if norm_pod == norm_rc and norm_pod in common_pos:
                            matched_pairs.append(f"{original_pod_pos[i]}↔{original_rc_identifiers[j]}")
                result["notes"] = f"Identifier match found: {', '.join(set(matched_pairs))}"
            else:
                result["notes"] = (
                    f"No matching identifiers found. POD has: {', '.join(original_pod_pos)}, "
                    f"Rate Con has: {', '.join(original_rc_identifiers)}"
                )

            result["rate_con_value"] = (
                f"{', '.join(original_rc_identifiers)}" if original_rc_identifiers else str(rc_val)
            )
        elif comp["type"] in ["fuzzy", "address"]:
            norm_pod = (
                normalize_address(pod_val) if comp["type"] == "address" else normalize_text(pod_val)
            )
            norm_rc = (
                normalize_address(rc_val) if comp["type"] == "address" else normalize_text(rc_val)
            )

            if fuzz.token_set_ratio(norm_pod, norm_rc) > 90:
                match = True
                result["notes"] = "High-confidence local fuzzy match (>90%)."
            else:
                logger.info(
                    "pod_vs_ratecon: local match inconclusive, asking LLM field=%s",
                    pod_key,
                )
                llm_match, llm_reason = ask_llm_for_semantic_match(pod_key, pod_val, rc_val)
                if llm_match:
                    match = True
                    result["notes"] = f"LLM confirmed match: {llm_reason}"
                else:
                    result["notes"] = f"LLM denied match: {llm_reason}"

        if not match and comp["key"] == "carrier_name":
            broker_name = ratecon_data.get("broker_name", "")
            if broker_name and pod_val:
                fuzzy_score = fuzz.token_set_ratio(str(pod_val).lower(), str(broker_name).lower())
                if fuzzy_score > 75:
                    match = True
                    result["status"] = "PASS"
                    result["notes"] = (
                        "PASS per business rule: POD carrier appears to be broker name "
                        f"(similarity: {fuzzy_score}%). Carrier can be missing/misidentified on POD."
                    )
                    logger.info(
                        "pod_vs_ratecon: carrier passed via broker similarity pod=%s score=%s",
                        pod_val,
                        fuzzy_score,
                    )

        if not match and comp["key"] == "carrier_name":
            pickup_location = ratecon_data.get("pickup_location", "")
            if pickup_location and pod_val:
                fuzzy_score = fuzz.token_set_ratio(str(pod_val).lower(), str(pickup_location).lower())
                if fuzzy_score > 70:
                    match = True
                    result["status"] = "PASS"
                    result["notes"] = (
                        "PASS per business rule: POD carrier appears to be pickup location "
                        f"(similarity: {fuzzy_score}%). Carrier can be missing/misidentified on POD."
                    )
                    logger.info(
                        "pod_vs_ratecon: carrier passed via pickup location similarity score=%s",
                        fuzzy_score,
                    )

        if match:
            result["status"] = "PASS"
        validation_report["field_validations"].append(result)

    pickup_location_result = next(
        (r for r in validation_report["field_validations"] if r["field"] == "pickup_location"),
        None,
    )
    pickup_address_result = next(
        (r for r in validation_report["field_validations"] if r["field"] == "pickup_address"),
        None,
    )

    if pickup_location_result and pickup_address_result:
        if pickup_location_result["status"] == "PASS" and pickup_address_result["status"] == "FAIL":
            orig_notes = pickup_address_result["notes"]
            pickup_address_result["status"] = "PASS"
            pickup_address_result["notes"] = (
                "Cross-validated PASS: Pickup location matched, so address is accepted. "
                f"Original check: {orig_notes}"
            )
            logger.info("pod_vs_ratecon: pickup address cross-validated via location match")
        elif pickup_address_result["status"] == "PASS" and pickup_location_result["status"] == "FAIL":
            orig_notes = pickup_location_result["notes"]
            pickup_location_result["status"] = "PASS"
            pickup_location_result["notes"] = (
                "Cross-validated PASS: Pickup address matched, so location is accepted. "
                f"Original check: {orig_notes}"
            )
            logger.info("pod_vs_ratecon: pickup location cross-validated via address match")

    delivery_location_result = next(
        (r for r in validation_report["field_validations"] if r["field"] == "destination_location"),
        None,
    )
    delivery_address_result = next(
        (r for r in validation_report["field_validations"] if r["field"] == "destination_address"),
        None,
    )

    if delivery_location_result and delivery_address_result:
        if delivery_location_result["status"] == "PASS" and delivery_address_result["status"] == "FAIL":
            orig_notes = delivery_address_result["notes"]
            delivery_address_result["status"] = "PASS"
            delivery_address_result["notes"] = (
                "Cross-validated PASS: Delivery location matched, so address is accepted. "
                f"Original check: {orig_notes}"
            )
            logger.info("pod_vs_ratecon: delivery address cross-validated via location match")
        elif delivery_address_result["status"] == "PASS" and delivery_location_result["status"] == "FAIL":
            orig_notes = delivery_location_result["notes"]
            delivery_location_result["status"] = "PASS"
            delivery_location_result["notes"] = (
                "Cross-validated PASS: Delivery address matched, so location is accepted. "
                f"Original check: {orig_notes}"
            )
            logger.info("pod_vs_ratecon: delivery location cross-validated via address match")

    if any(r["status"] == "FAIL" for r in validation_report["field_validations"]):
        validation_report["overall_status"] = "FAIL"

    return validation_report


def generate_validation_summary(
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
) -> dict[str, Any]:
    """
    LLM-powered validation summary and confidence score (legacy prompt preserved).
    """
    signature_present = pod_analysis.get("signature_present", False)
    stamp_present = pod_analysis.get("stamp_present", False)
    delivery_confirmed = pod_analysis.get("delivery_confirmed", False)
    delivery_confirmation_reasoning = pod_analysis.get("delivery_confirmation_reasoning", "")

    prompt = f"""Analyze this POD vs RateCon cross-validation result and provide a concise 2-line summary with confidence score.

VALIDATION RESULTS:
{json.dumps(cross_validation, indent=2)}

POD ANALYSIS DATA:
- Signature Present: {signature_present}
- Stamp Present: {stamp_present}
- Delivery Confirmed: {delivery_confirmed}
- Delivery Confirmation Reasoning: {delivery_confirmation_reasoning}

INSTRUCTIONS:
1. Provide exactly 2 lines (no more, no less):
   - Line 1: Field matches/discrepancies summary
   - Line 2: Delivery status and key business insights

2. Calculate confidence score (0.0 to 1.0) using simple 50/50 weighting:
   - 50% weight: Signature/Stamp/Delivery confirmations (higher points for present/confirmed)
   - 50% weight: Field validation results (higher points for PASS status)

   Simple scoring logic:
   - Signature present: +0.15 points
   - Stamp present: +0.15 points
   - Delivery confirmed: +0.20 points
   - Each field validation PASS: +0.50 points divided by total fields
   - Start from base 0.1, cap at 1.0

3. Do NOT mention "PASS", "FAIL", or "Line 1/Line 2" in summary. Be direct and business-focused.

RESPONSE FORMAT (JSON only):
{{
  "summary": "Field validation summary line.\\nDelivery confirmation and business insights line.",
  "confidence_score": 0.85
}}

Be extremely concise."""

    system = (
        "You are a logistics validation expert. Provide concise, accurate summaries of "
        "POD vs RateCon validation results for freight operations. Always respond with valid JSON."
    )

    try:
        llm_result = chat_json(system, prompt, temperature=0.1, timeout_s=120.0)
        summary = str(llm_result.get("summary", "Validation analysis completed")).strip()
        confidence_score = float(llm_result.get("confidence_score", 0.5))
        confidence_score = max(0.0, min(1.0, confidence_score))
        logger.info(
            "pod_vs_ratecon: generated validation summary confidence=%s",
            confidence_score,
        )
        return {"summary": summary, "confidence_score": confidence_score}
    except LLMClientError as exc:
        logger.warning("pod_vs_ratecon: summary LLM failed err=%s", exc)
        return {
            "summary": "Validation analysis completed - LLM summary generation failed",
            "confidence_score": 0.5,
        }
    except Exception:
        logger.exception("pod_vs_ratecon: summary generation failed")
        return {
            "summary": "Validation analysis completed - summary generation failed",
            "confidence_score": 0.5,
        }
