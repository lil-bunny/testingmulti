"""
POD PDF → single-call direct-PDF extraction.

Flow: size/page guard -> one ``chat_pdf_json`` call against the whole
merged POD PDF using the Hub ``pod-pdf-extraction`` prompt -> preserve
page-level evidence for the Turvo-aware scoring stage.

RATE_CONFIRMATION pages may be present in the LLM response for audit;
trimming for S3 upload happens after this extraction in the graph.

No flat document-level LLM reconciliation is used for PoD decisions. The
Turvo-aware scoring stage owns PO, stop, and delivery-proof reconciliation.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.integrations.langsmith.types import PromptTraceMetadata
from app.services.prompt_service import resolve_pod_pdf_prompts
from app.tools.llm_credentials import resolve_llm_credentials
from app.tools.llm_client import LLMClientError, chat_pdf_json
from app.tools.pdf_page_text_extractor import pdf_page_count
from app.tools.pdf_to_images import PdfTooLargeError

logger = logging.getLogger(__name__)

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
    _unused_legacy_pod_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build raw POD observations from LLM ``pages[]`` only.

    Stop-aware reconciliation is intentionally deferred until Turvo inputs are
    available in the scoring node.
    """
    page_list = [p for p in pages if isinstance(p, dict)] if isinstance(pages, list) else []

    delivery_signature_present = False
    pickup_signature_present = False
    reference_values: set[str] = set()
    damage_detected = False
    damage_detail = ""
    refused_delivery = False

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
        if page.get("refused_delivery"):
            refused_delivery = True

    stop_times = [
        entry
        for page in page_list
        for entry in (page.get("stop_times") or [])
        if isinstance(entry, dict)
    ]
    pickup_date = _first_stop_time(stop_times, ("pickup_checkin_time", "pickup_checkout_time"))
    delivery_date = _first_stop_time(stop_times, ("delivery_checkin_time", "delivery_checkout_time"))

    return {
        "delivery_signature_present": delivery_signature_present,
        "pickup_signature_present": pickup_signature_present,
        "extracted_reference_numbers": sorted(reference_values),
        "pickup_date": pickup_date,
        "delivery_date": delivery_date,
        "pallets_shipped": _pallets_shipped_from_pages(page_list),
        "damage_detected": damage_detected,
        "damage_detail": damage_detail or None,
        "refused_delivery": refused_delivery,
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


def extract_from_pdf_path(
    pdf_path: str,
    *,
    broker_name: str | None = None,
    tenant_settings: dict[str, Any] | None = None,
    model_label: str | None = None,
) -> tuple[list[Any], dict[str, Any], list[str], dict[str, Any], dict[str, Any]]:
    """
    Single-call PDF extraction: size/page guard -> ``chat_pdf_json`` -> pages.

    Returns ``(page_details, {}, [], {}, raw_llm_response)`` while callers
    migrate to the page-evidence-only return contract.
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
    credentials = resolve_llm_credentials(workflow_name="pod_lifecycle")

    try:
        raw_response = chat_pdf_json(
            pdf_prompts.system,
            pdf_prompts.user or " ",
            pdf_bytes,
            credentials=credentials,
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
        return error_row, {}, [], {}, {}

    if not isinstance(raw_response, dict):
        raw_response = {}
    pages = raw_response.get("pages")
    page_details = wrap_pages_as_page_details(pages, load_id)

    if not page_details:
        logger.warning(
            "pod_extraction: PDF response missing usable page evidence load_id=%s",
            load_id,
        )
        page_details = [
            {
                "page_number": 1,
                "timestamp": datetime.now().isoformat(),
                "error": "LLM response missing usable page evidence",
                "load_id": load_id,
                "error_category": "empty_response",
            }
        ]
        return page_details, {}, [], {}, raw_response

    logger.info(
        "pod_extraction: PDF extraction complete load_id=%s pages=%s model=%s",
        load_id,
        len(page_details),
        model_label,
    )
    return page_details, {}, [], {}, raw_response


