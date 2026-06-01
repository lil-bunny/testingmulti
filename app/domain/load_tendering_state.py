"""``state.data['tender']`` shape for load-tendering workflows (order + product lines)."""

from __future__ import annotations

from typing import Any

from app.services.tender_service import TenderOrderPlusProducts

TENDER_STATE_KEY = "tender"


def get_tender(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the nested tender blob from workflow state / Celery payload."""
    raw = data.get(TENDER_STATE_KEY)
    if isinstance(raw, dict):
        return raw
    return None


def set_tender(data: dict[str, Any], tender: dict[str, Any]) -> None:
    data[TENDER_STATE_KEY] = tender


def get_tender_products(tender: dict[str, Any]) -> list[dict[str, Any]]:
    raw = tender.get("tender_products")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, dict)]


def order_number_from_data(data: dict[str, Any]) -> str:
    tender = get_tender(data)
    if tender:
        num = str(tender.get("order_number") or "").strip()
        if num:
            return num
    row = data.get("tender_row")
    if isinstance(row, dict):
        num = str(row.get("order_number") or "").strip()
        if num:
            return num
    return str(data.get("order_number") or data.get("load_id") or "").strip()


def load_type_from_data(data: dict[str, Any]) -> str:
    tender = get_tender(data)
    if tender:
        raw = str(tender.get("load_type") or "").strip()
        if raw:
            return raw.lower()
    return str(data.get("load_type") or "").strip().lower()


def tender_from_ingest_row(tender_row: dict[str, Any], *, order_number: str) -> dict[str, Any]:
    """Initial tender state from spreadsheet projection (pre-``calculate_tender_params``)."""
    customer_name = str(
        tender_row.get("customer_name") or tender_row.get("customer_match") or ""
    ).strip()
    return {
        "order_number": order_number,
        "customer_name": customer_name,
        "po_number": str(tender_row.get("po_number") or "").strip(),
        "pack_code": str(tender_row.get("pack_code") or "").strip(),
        "tender_products": [],
    }


def tender_from_read_order(
    tender_order_plus_products: TenderOrderPlusProducts,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build tender blob after ``read_order`` (reminder / escalation paths)."""
    order = tender_order_plus_products["tender"]
    products = tender_order_plus_products["products"]
    base: dict[str, Any] = dict(existing) if isinstance(existing, dict) else {}
    base.update(
        {
            "order_number": str(order.get("order_number") or base.get("order_number") or ""),
            "customer_name": str(
                order.get("customer_name") or base.get("customer_name") or ""
            ),
            "load_type": str(order.get("load_type") or base.get("load_type") or "")
            .strip()
            .lower(),
            "tender_products": products,
        }
    )
    metadata = order.get("metadata") if isinstance(order.get("metadata"), dict) else {}
    po = str(metadata.get("po_number") or "").strip()
    if po and not base.get("customer_po"):
        base["customer_po"] = po
    return base


def ingest_pack_code(data: dict[str, Any]) -> str:
    tender = get_tender(data)
    if tender:
        code = str(tender.get("pack_code") or "").strip()
        if code:
            return code
    row = data.get("tender_row")
    if isinstance(row, dict):
        return str(row.get("pack_code") or "").strip()
    return ""
