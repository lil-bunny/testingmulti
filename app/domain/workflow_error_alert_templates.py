"""Render tenant workflow error alert templates."""

from __future__ import annotations

from typing import Any

from app.domain.load_tendering_state import (
    get_tender,
    ingest_delivery_address_code,
    order_number_from_data,
)


def customer_po_from_data(data: dict[str, Any]) -> str:
    """Customer purchase order from tender, import row, or event metadata when present."""
    tender = get_tender(data)
    if tender:
        po = str(tender.get("customer_po") or tender.get("po_number") or "").strip()
        if po:
            return po
    row = data.get("tender_row")
    if isinstance(row, dict):
        for key in ("customer_po", "po_number"):
            po = str(row.get(key) or "").strip()
            if po:
                return po
    metadata = data.get("metadata")
    if isinstance(metadata, dict):
        po = str(metadata.get("po_number") or metadata.get("customer_po") or "").strip()
        if po:
            return po
    return ""


def build_workflow_error_alert_template_context(
    *,
    data: dict[str, Any],
    error: dict[str, Any],
    workflow_lifecycle_id: str,
    workflow_run_id: str,
) -> dict[str, str]:
    """Values available to alert subject and body templates for one failure."""
    customer_po = customer_po_from_data(data)
    order_number = order_number_from_data(data)
    failure_reason = str(error.get("message") or "").strip()
    error_code = str(error.get("code") or "").strip()
    error_category = str(error.get("category") or "").strip()

    delivery_address_code = ingest_delivery_address_code(data)

    delivery_location_code_block = ""
    if delivery_address_code:
        delivery_location_code_block = (
            "<p><strong>Delivery Location Code:</strong> "
            f"{delivery_address_code}</p>"
        )

    return {
        "customer_po": customer_po,
        "po_number": customer_po,
        "order_number": order_number,
        "failure_reason": failure_reason,
        "error_code": error_code,
        "error_category": error_category,
        "delivery_address_code": delivery_address_code,
        "delivery_location_code_block": delivery_location_code_block,
        "workflow_lifecycle_id": workflow_lifecycle_id,
        "workflow_run_id": workflow_run_id,
    }


def format_workflow_error_alert_template(
    template: str,
    context: dict[str, str],
) -> str:
    """Apply ``str.format`` placeholders; unknown keys become empty strings."""
    class _SafeFormatMap(dict[str, str]):
        def __missing__(self, key: str) -> str:
            return ""

    return template.format_map(_SafeFormatMap(context))
