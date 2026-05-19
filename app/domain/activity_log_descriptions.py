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
