"""
POD vs Rate Confirmation cross-validation (rule engine + optional LLM semantic checks).

Ported from ``old/agents/pod_validator/pod_validation.py`` and
``old/services/pod_validation_service.py`` (business rules preserved).
Uses ``chat_json`` with app ``LLM_*`` settings; fuzzy matching via ``thefuzz``.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from thefuzz import fuzz

from app.domain.prompt_step_keys import POD_VS_RATECON_SEMANTIC_MATCH, POD_VS_RATECON_SUMMARY
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import (
    PromptService,
    resolve_pod_vs_ratecon_semantic_match_prompts,
    resolve_pod_vs_ratecon_summary_prompts,
)
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


def ask_llm_for_semantic_match(
    field_type: str,
    value1: str,
    value2: str,
    *,
    tenant_settings: dict[str, Any] | None = None,
    prompt_service: PromptService | None = None,
) -> tuple[bool, str]:
    """Ask an LLM if two field values are semantically equivalent (Hub or JSON fallback)."""
    try:
        rendered, prompt_metadata = resolve_pod_vs_ratecon_semantic_match_prompts(
            tenant_settings,
            field_type,
            value1,
            value2,
            prompt_service=prompt_service,
        )
        prompt_trace = PromptTraceMetadata.from_load(
            POD_VS_RATECON_SEMANTIC_MATCH,
            prompt_metadata,
        )
        llm_response = chat_json(
            rendered.system,
            rendered.user,
            temperature=0.1,
            prompt_trace=prompt_trace,
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


def validate_pod_against_ratecon(
    pod_data: dict,
    ratecon_data: dict,
    *,
    tenant_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Compares reconciled POD data against Rate Confirmation data using the hybrid approach.
    """
    validation_report: dict[str, Any] = {
        "overall_status": "PASS",
        "field_validations": [],
    }

    comparisons = [
        {"key": "po_number", "rc_key": "po_number", "type": "po_number"},
        {"key": "pickup_location", "rc_key": "pickup_location", "type": "fuzzy"},
        {"key": "pickup_address", "rc_key": "pickup_address", "type": "address"},
        {"key": "destination_location", "rc_key": "delivery_location", "type": "fuzzy"},
        {"key": "destination_address", "rc_key": "delivery_address", "type": "address"},
    ]

    for comp in comparisons:
        pod_key, rc_key = comp["key"], comp["rc_key"]
        pod_val, rc_val = pod_data.get(pod_key), ratecon_data.get(rc_key)

        if pod_val is None:
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
                llm_match, llm_reason = ask_llm_for_semantic_match(
                    pod_key,
                    pod_val,
                    rc_val,
                    tenant_settings=tenant_settings,
                )
                if llm_match:
                    match = True
                    result["notes"] = f"LLM confirmed match: {llm_reason}"
                else:
                    result["notes"] = f"LLM denied match: {llm_reason}"

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
    *,
    tenant_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """LLM-powered validation summary and confidence score (Hub or JSON fallback)."""
    try:
        rendered, prompt_metadata = resolve_pod_vs_ratecon_summary_prompts(
            tenant_settings,
            cross_validation,
            pod_analysis,
        )
        prompt_trace = PromptTraceMetadata.from_load(POD_VS_RATECON_SUMMARY, prompt_metadata)
        llm_result = chat_json(
            rendered.system,
            rendered.user,
            temperature=0.1,
            prompt_trace=prompt_trace,
        )
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
