"""Human-readable ``activity_logs.description`` strings."""

from __future__ import annotations


def format_tender_created_action(
    *,
    tender_id: str,
    order_number: str,
    customer_name: str,
) -> str:
    order = (order_number or "").strip() or tender_id
    customer = (customer_name or "").strip() or "Unknown"
    return f"Tender {order} created for {customer}"


def format_status_updated_to_processing() -> str:
    return "Status updated to Processing"


def format_tender_sent_to_tenant_action(*, tender_id: str) -> str:
    tid = (tender_id or "").strip() or "unknown"
    return f"Tender email sent to vendor (tender_id={tid})"


def format_tender_sent_to_tenant_status_change() -> str:
    return "Tender email sent to vendor"


def format_carrier_ack_llm_action(
    *,
    decision: str,
    reason: str,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    reason_s = (reason or "").strip() or "no reason"
    return f"Carrier ack LLM classified reply as {decision}{conf}: {reason_s}"
