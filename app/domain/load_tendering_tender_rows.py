"""Map spreadsheet-projected tender dicts into ``tenders`` row payloads for inserts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.models.load_type import LoadType


def _parse_optional_date(val: Any) -> date | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.date()
    if isinstance(val, date):
        return val
    text = str(val).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        except ValueError:
            return None


def _parse_order_quantity(val: Any) -> Decimal | None:
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val
    try:
        d = Decimal(str(val))
        if not d.is_finite():
            return None
        return d
    except (InvalidOperation, ValueError):
        return None


def _pack_code_uuid(val: Any) -> str | None:
    if val is None:
        return None
    raw = str(val).strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError:
        return None


def projected_row_to_tender_insert(row: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build kwargs for ``TendersRepository.insert_batch`` (excluding tenant/data_import_id).

    Returns ``None`` when required fields are missing or invalid. Optional ``pack_code_id``
    is omitted from SQL when not a valid UUID.
    """
    order_number = str(row.get("order_number") or "").strip()
    if not order_number:
        return None

    customer_name = str(row.get("customer_match") or "").strip()
    product_name = str(row.get("product_name") or "").strip()
    if not customer_name or not product_name:
        return None

    qty = _parse_order_quantity(row.get("order_quantity"))
    if qty is None:
        return None

    delivery = _parse_optional_date(row.get("delivery_date"))
    shipping = _parse_optional_date(row.get("shipping_date"))
    pack_id = _pack_code_uuid(row.get("pack_code_id"))
    po_number = str(row.get("po_number") or "").strip()
    metadata: dict[str, Any] = {"po_number": po_number} if po_number else {}

    return {
        "order_number": order_number,
        "customer_name": customer_name,
        "product_name": product_name,
        "order_quantity": qty,
        "shipping_date": shipping,
        "delivery_date": delivery,
        "pickup_location_id": None,
        "delivery_location_id": None,
        "pack_code_id": pack_id,
        "status": "po_imported",
        "load_type": LoadType.LTL.value,
        "metadata": metadata,
    }
