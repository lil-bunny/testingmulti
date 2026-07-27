"""
POD PDF → single-call direct-PDF extraction.

Flow: size/page guard -> one ``chat_pdf_json`` call against the whole
(stripped/merged) POD PDF using the Hub ``pod-pdf-extraction`` prompt -> map
the LLM's own ``reconciled`` block into the flat ``pod_data`` shape downstream
(``pod_scoring``, activity/notify services) already expects.

No per-page vision fan-out, no Python page reconciliation: the LLM reasons
across the whole document in one request and returns both per-page evidence
(``pages``) and a document-level ``reconciled`` object; we trust ``reconciled``
for field values and recompute only the ``delivery_confirmed`` boolean in code
so it stays a deterministic business rule.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_pod_pdf_prompts
from app.tools.llm_client import LLMClientError, chat_pdf_json
from app.tools.pdf_page_text_extractor import pdf_page_count
from app.tools.pdf_to_images import PdfTooLargeError

logger = logging.getLogger(__name__)

_MAPPED_FIELD_KEYS = (
    "carrier_name",
    "po_number",
    "pickup_location",
    "pickup_address",
    "destination_location",
    "destination_address",
    "stamp_company_name",
)


def _str_or_empty(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    return s if s and s.lower() not in ("null", "none", "n/a") else ""


def _normalize_stop_time_to_iso(val: str) -> str:
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


def is_valid_delivery_confirmation(data: dict[str, Any]) -> bool:
    """A delivery is confirmed if there is a valid receiver signature OR a stamp."""
    return bool(data.get("signature_present", False) or data.get("stamp_present", False))


def validate_pod_consistency(final_data: dict[str, Any]) -> list[str]:
    """Validates the final reconciled data for logical issues."""
    issues = []
    if not is_valid_delivery_confirmation(final_data):
        issues.append("No concrete proof of delivery (receiver signature or stamp required).")
    return issues


def map_reconciled_to_pod_data(
    reconciled: dict[str, Any],
    broker_name: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Map the Hub ``reconciled`` block to the flat ``pod_data`` shape.

    ``po_number``: join all distinct values with ``", "`` (multiple ``fields``
    entries with the same key are expected). Other mapped keys: highest
    ``confidence`` entry wins (first one on a tie). ``delivery_confirmed`` is
    recomputed from the mapped signature/stamp flags, never trusted from the
    LLM's own ``reconciled.delivery_confirmed``.
    """
    final_data: dict[str, Any] = {}
    reconciliation_log: dict[str, Any] = {}

    fields = reconciled.get("fields") if isinstance(reconciled.get("fields"), list) else []
    by_key: dict[str, list[dict[str, Any]]] = {}
    for field in fields:
        if not isinstance(field, dict):
            continue
        key = field.get("key")
        if key not in _MAPPED_FIELD_KEYS:
            continue
        by_key.setdefault(key, []).append(field)

    broker_lower = (broker_name or "").strip().lower()

    po_entries = by_key.get("po_number", [])
    if po_entries:
        all_pos: set[str] = set()
        for entry in po_entries:
            for po in str(entry.get("value") or "").split(","):
                po = po.strip()
                if po and len(po) >= 2 and po.lower() not in ("null", "none", "n/a"):
                    all_pos.add(po)
        if all_pos:
            final_data["po_number"] = ", ".join(sorted(all_pos))
            reconciliation_log["po_number"] = (
                f"Aggregated {len(all_pos)} unique PO number(s) from reconciled.fields."
            )

    for key in ("carrier_name", "pickup_location", "pickup_address", "destination_location", "destination_address", "stamp_company_name"):
        entries = [e for e in by_key.get(key, []) if _str_or_empty(e.get("value"))]
        if key == "carrier_name" and broker_lower:
            filtered = [e for e in entries if broker_lower not in str(e.get("value")).lower()]
            if len(filtered) < len(entries):
                logger.info(
                    "pod_extraction: filtered broker from carrier candidates broker=%s",
                    broker_name,
                )
            entries = filtered
        if not entries:
            if key == "carrier_name":
                final_data["carrier_name"] = None
                broker_note = (
                    f" (Note: Broker '{broker_name}' was excluded from carrier selection)"
                    if broker_lower
                    else ""
                )
                reconciliation_log["carrier_name"] = f"No valid carrier found by LLM{broker_note}."
            continue
        winner = max(entries, key=lambda e: e.get("confidence") or 0)
        final_data[key] = _str_or_empty(winner.get("value"))
        reconciliation_log[key] = (
            f"Selected '{final_data[key]}' (confidence={winner.get('confidence')})."
        )

    proof = reconciled.get("proof_of_receipt") if isinstance(reconciled.get("proof_of_receipt"), dict) else {}
    final_data["signature_present"] = bool(proof.get("has_receiver_signature"))
    final_data["stamp_present"] = bool(proof.get("has_stamp"))
    reconciliation_log["signature_present"] = (
        f"Receiver signature evidence: {proof.get('receiver_signature_location') or 'N/A'}"
        if final_data["signature_present"]
        else "No valid receiver signature/acceptance found."
    )
    reconciliation_log["stamp_present"] = (
        "Company stamp evidence present." if final_data["stamp_present"] else "No stamp found."
    )

    # Deterministic business rule (Q4) — never trust the LLM's own
    # ``reconciled.delivery_confirmed`` flag.
    final_data["delivery_confirmed"] = is_valid_delivery_confirmation(final_data)
    final_data["delivery_confirmation_reasoning"] = (
        str(proof.get("delivery_confirmation_reasoning") or "").strip()
        or "No delivery confirmation evidence found by LLM"
    )

    stop_times_agg = []
    raw_stop_times = reconciled.get("stop_times")
    if isinstance(raw_stop_times, list):
        for obj in raw_stop_times:
            if not isinstance(obj, dict):
                continue
            normalized = {}
            for k in (
                "pickup_checkin_time",
                "pickup_checkout_time",
                "delivery_checkin_time",
                "delivery_checkout_time",
            ):
                s = _str_or_empty(obj.get(k))
                normalized[k] = _normalize_stop_time_to_iso(s) if s else ""
            stop_times_agg.append(normalized)
    final_data["stop_times"] = stop_times_agg
    if stop_times_agg:
        reconciliation_log["stop_times"] = f"Mapped {len(stop_times_agg)} stop(s) from reconciled.stop_times."

    return final_data, reconciliation_log


def _page_proof(page: dict[str, Any]) -> dict[str, Any]:
    proof = page.get("proof_of_receipt")
    return proof if isinstance(proof, dict) else {}


def _page_reference_values(page: dict[str, Any]) -> list[str]:
    """Every labeled reference-id value on a page, plus its delivery-sticker number."""
    values: list[str] = []
    raw = page.get("reference_ids")
    if isinstance(raw, list):
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            value = _str_or_empty(entry.get("value"))
            if value:
                values.append(value)
    delivery_number = _str_or_empty(_page_proof(page).get("delivery_number"))
    if delivery_number:
        values.append(delivery_number)
    return values


def _pallets_shipped_from_pages(pages: list[dict[str, Any]]) -> int | None:
    values: list[int] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        try:
            raw = page.get("pallets_shipped")
            if raw is not None:
                values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return max(values) if values else None


def _first_stop_time(stop_times: list[Any], keys: tuple[str, str]) -> str | None:
    for entry in stop_times:
        if not isinstance(entry, dict):
            continue
        for key in keys:
            val = _str_or_empty(entry.get(key))
            if val:
                return val
    return None


def derive_pod_scoring_observations(
    pages: Any,
    final_pod_data: dict[str, Any],
) -> dict[str, Any]:
    """
    Build ``pod_observations`` for ``score_pod`` from LLM ``pages[]`` + ``pod_data``.

    Delivery/pickup signature flags are a deterministic OR over stop-attributed
    pages (never a document-level LLM opinion), matching ``delivery_confirmed``.
    """
    page_list = [p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []

    delivery_signature_present = False
    pickup_signature_present = False
    reference_values: set[str] = set()
    damage_detected = False
    damage_detail = ""

    for page in page_list:
        proof = _page_proof(page)
        has_evidence = bool(
            proof.get("has_receiver_signature")
            or proof.get("has_stamp")
            or proof.get("has_delivery_sticker")
        )
        attribution = str(page.get("page_stop_attribution") or "").strip().lower()
        owner = str(page.get("signature_owner") or "").strip().lower()

        if attribution == "delivery" and owner == "receiver" and has_evidence:
            delivery_signature_present = True
        if attribution == "pickup" and (proof.get("has_receiver_signature") or proof.get("has_stamp")):
            pickup_signature_present = True

        reference_values.update(_page_reference_values(page))

        if page.get("damage_detected") and not damage_detected:
            damage_detected = True
            damage_detail = _str_or_empty(page.get("damage_detail"))

    for po in str(final_pod_data.get("po_number") or "").split(","):
        po = po.strip()
        if po:
            reference_values.add(po)

    raw_stop_times = final_pod_data.get("stop_times")
    stop_times = raw_stop_times if isinstance(raw_stop_times, list) else []
    pickup_date = _first_stop_time(stop_times, ("pickup_checkin_time", "pickup_checkout_time"))
    delivery_date = _first_stop_time(stop_times, ("delivery_checkin_time", "delivery_checkout_time"))

    return {
        "delivery_signature_present": delivery_signature_present,
        "pickup_signature_present": pickup_signature_present,
        "extracted_reference_numbers": sorted(reference_values),
        "pickup_date": pickup_date,
        "delivery_date": delivery_date,
        "shipper_name": final_pod_data.get("pickup_location"),
        "shipper_address": final_pod_data.get("pickup_address"),
        "consignee_name": final_pod_data.get("destination_location"),
        "consignee_address": final_pod_data.get("destination_address"),
        "pallets_shipped": _pallets_shipped_from_pages(page_list),
        "damage_detected": damage_detected,
        "damage_detail": damage_detail or None,
    }


def wrap_pages_as_page_details(pages: Any, load_id: str) -> list[dict[str, Any]]:
    """Wrap Hub ``pages[]`` items as the legacy ``{page_number, extracted_data, load_id}`` shape."""
    if not isinstance(pages, list):
        return []
    wrapped = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_number = page.get("page_number")
        wrapped.append(
            {
                "page_number": page_number if isinstance(page_number, int) else 0,
                "extracted_data": page,
                "load_id": load_id,
            }
        )
    return wrapped


def pdf_document_confidence_score(
    pod_data: dict[str, Any],
    validation_issues: list[str],
    reconciled: dict[str, Any],
) -> float:
    """
    Document-level heuristic confidence (0..1).

    Placeholder for commit 1 only — no business-logic change intended. Blends
    delivery confirmation, mapped-field completeness, and average LLM field
    confidence from ``reconciled.fields``; penalized by validation issues.
    Commit 2 (POD-vs-Turvo scoring) replaces this with PO-level scoring.
    """
    completeness_keys = (
        "carrier_name",
        "po_number",
        "pickup_location",
        "pickup_address",
        "destination_location",
        "destination_address",
    )
    present = sum(1 for k in completeness_keys if pod_data.get(k))
    completeness_ratio = present / len(completeness_keys)

    fields = reconciled.get("fields") if isinstance(reconciled.get("fields"), list) else []
    confidences = [
        float(f.get("confidence"))
        for f in fields
        if isinstance(f, dict) and isinstance(f.get("confidence"), (int, float))
    ]
    avg_field_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.5

    if pod_data.get("delivery_confirmed"):
        base = 0.35 + 0.35 * completeness_ratio + 0.20 * avg_field_confidence
    else:
        base = 0.20 + 0.25 * completeness_ratio + 0.15 * avg_field_confidence
    if validation_issues:
        base *= 0.85
    return max(0.0, min(1.0, round(base, 4)))


def extract_from_pdf_path(
    pdf_path: str,
    *,
    broker_name: str | None = None,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
) -> tuple[list[Any], dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    """
    Single-call PDF extraction: size/page guard -> ``chat_pdf_json`` -> map
    ``reconciled`` -> flat ``pod_data`` -> validate.

    Returns ``(page_details, pod_data, validation_issues, reconciliation_log, raw_llm_response)``.
    Raises ``PdfTooLargeError`` when the PDF exceeds ``POD_PDF_MAX_BYTES`` /
    ``POD_PDF_MAX_PAGES`` (fail closed — no compression fallback here).
    """
    from app.domain.prompt_step_keys import POD_PDF_EXTRACTION

    load_id = Path(pdf_path).stem.replace(" POD", "").replace("_", "")

    with open(pdf_path, "rb") as f:
        pdf_bytes = f.read()

    byte_len = len(pdf_bytes)
    if byte_len > settings.POD_PDF_MAX_BYTES:
        raise PdfTooLargeError(
            f"POD PDF too large for direct extraction: {byte_len} bytes "
            f"(max {settings.POD_PDF_MAX_BYTES})"
        )
    page_count = pdf_page_count(pdf_bytes)
    if page_count > settings.POD_PDF_MAX_PAGES:
        raise PdfTooLargeError(
            f"POD PDF has too many pages for direct extraction: {page_count} "
            f"(max {settings.POD_PDF_MAX_PAGES})"
        )

    pdf_prompts, prompt_metadata = resolve_pod_pdf_prompts(tenant_settings)
    prompt_trace = PromptTraceMetadata.from_load(POD_PDF_EXTRACTION, prompt_metadata)

    try:
        raw_response = chat_pdf_json(
            pdf_prompts.system,
            pdf_prompts.user or " ",
            pdf_bytes,
            filename=f"{load_id or 'document'}.pdf",
            prompt_trace=prompt_trace,
        )
    except LLMClientError as exc:
        logger.warning("pod_extraction: PDF extraction LLM call failed load_id=%s err=%s", load_id, exc)
        error_row = [
            {
                "page_number": 1,
                "timestamp": datetime.now().isoformat(),
                "error": f"API Error: {exc}",
                "load_id": load_id,
                "error_category": "api_error",
            }
        ]
        final_pod_data, reconciliation_log = map_reconciled_to_pod_data({}, broker_name)
        validation_issues = validate_pod_consistency(final_pod_data)
        return error_row, final_pod_data, validation_issues, reconciliation_log, {}

    if not isinstance(raw_response, dict):
        raw_response = {}
    reconciled = raw_response.get("reconciled")
    reconciled = reconciled if isinstance(reconciled, dict) else {}
    has_usable_reconciled = bool(reconciled.get("fields")) or bool(reconciled.get("proof_of_receipt"))

    pages = raw_response.get("pages")
    page_details = wrap_pages_as_page_details(pages, load_id)

    if not has_usable_reconciled:
        logger.warning(
            "pod_extraction: PDF response missing usable reconciled block load_id=%s",
            load_id,
        )
        if not page_details:
            page_details = [
                {
                    "page_number": 1,
                    "timestamp": datetime.now().isoformat(),
                    "error": "LLM response missing usable 'reconciled' data",
                    "load_id": load_id,
                    "error_category": "empty_response",
                }
            ]
        final_pod_data, reconciliation_log = map_reconciled_to_pod_data({}, broker_name)
        validation_issues = validate_pod_consistency(final_pod_data)
        return page_details, final_pod_data, validation_issues, reconciliation_log, raw_response

    final_pod_data, reconciliation_log = map_reconciled_to_pod_data(reconciled, broker_name)
    document_summary = raw_response.get("document_summary")
    if isinstance(document_summary, dict) and document_summary.get("notes"):
        reconciliation_log["document_summary_notes"] = str(document_summary["notes"])
    validation_issues = validate_pod_consistency(final_pod_data)

    logger.info(
        "pod_extraction: PDF extraction complete load_id=%s pages=%s model=%s",
        load_id,
        len(page_details),
        model_label,
    )
    if validation_issues:
        logger.warning(
            "pod_extraction: validation issues load_id=%s issues=%s",
            load_id,
            validation_issues,
        )

    return page_details, final_pod_data, validation_issues, reconciliation_log, raw_response


def pod_confidence_score(
    page_results: list[Any],
    final_pod_data: dict[str, Any],
    validation_issues: list[str],
    raw_llm_response: dict[str, Any] | None = None,
) -> float:
    """Document-level confidence — see ``pdf_document_confidence_score``."""
    _ = page_results
    reconciled = (raw_llm_response or {}).get("reconciled")
    reconciled = reconciled if isinstance(reconciled, dict) else {}
    return pdf_document_confidence_score(final_pod_data, validation_issues, reconciled)
