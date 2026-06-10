"""Map spreadsheet-projected tender dicts into ``tenders`` / ``tender_products`` payloads."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from app.domain.spreadsheet_cells import identifier_string_from_cell
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


def parse_order_position(val: Any) -> int | None:
    """Parse Excel order position as a positive integer (e.g. ``10.0`` -> ``10``)."""
    if val is None:
        return None
    if isinstance(val, bool):
        return None
    if isinstance(val, int):
        return val if val > 0 else None
    if isinstance(val, float):
        if not math.isfinite(val) or val != int(val):
            return None
        pos = int(val)
        return pos if pos > 0 else None
    text = str(val).strip()
    if not text:
        return None
    try:
        d = Decimal(text)
        if not d.is_finite() or d != d.to_integral_value():
            return None
        pos = int(d)
        return pos if pos > 0 else None
    except (InvalidOperation, ValueError):
        return None


def dedupe_projected_rows_by_order_and_position(
    rows: list[dict[str, Any]],
) -> list[tuple[int, dict[str, Any]]]:
    """
    Keep at most one row per ``(order_number, order_position)``; first spreadsheet row wins.

    Rows missing a valid order number or order position are omitted.
    """
    seen: set[tuple[str, int]] = set()
    kept: list[tuple[int, dict[str, Any]]] = []
    for i, row in enumerate(rows):
        order_number = identifier_string_from_cell(row.get("order_number")) or ""
        pos = parse_order_position(row.get("order_position"))
        if not order_number or pos is None:
            continue
        key = (order_number, pos)
        if key in seen:
            continue
        seen.add(key)
        kept.append((i, row))
    return kept


_KG_ALIASES = frozenset({"kg", "kgm", "kilogram", "kilograms"})
_LB_ALIASES = frozenset({"lb", "lbs", "pound", "pounds"})


def parse_weight_unit(val: Any) -> str | None:
    """Normalize Ship Schedule ``ME`` cell to ``kg`` or ``lb`` enum label."""
    if val is None:
        return None
    text = str(val).strip().casefold()
    if not text:
        return None
    if text in _KG_ALIASES:
        return "kg"
    if text in _LB_ALIASES:
        return "lb"
    return None


def resolve_pack_code_id(
    row: dict[str, Any],
    *,
    active_pack_code_index: dict[str, str] | None = None,
) -> str | None:
    """
    Resolve ``pack_codes.id`` from a projected row.

    Prefer explicit UUID in ``pack_code_id`` (tests). Otherwise match trimmed ``pack_code``
    text exactly against ``active_pack_code_index`` (active rows only).
    """
    explicit = _pack_code_uuid(row.get("pack_code_id"))
    if explicit:
        return explicit
    text = str(row.get("pack_code") or "").strip()
    if not text or not active_pack_code_index:
        return None
    return active_pack_code_index.get(text)


def projected_row_to_tender_insert(
    row: dict[str, Any],
    *,
    customer_name: str | None = None,
    customer_name_source: str | None = None,
    active_pack_code_index: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Build kwargs for ``TendersRepository.insert_batch`` (excluding tenant/data_import_id).

    Header-only: no product fields. Workflow enqueue when insert returns ``created=True``.
    ``customer_name`` is supplied by ingest (delivery locations column J); not KDMATCH.
    """
    _ = active_pack_code_index
    order_number = identifier_string_from_cell(row.get("order_number")) or ""
    if not order_number:
        return None

    resolved_customer = str(customer_name or "").strip()
    if not resolved_customer:
        return None

    delivery = _parse_optional_date(row.get("delivery_date"))
    shipping = _parse_optional_date(row.get("shipping_date"))
    po_number = identifier_string_from_cell(row.get("po_number")) or ""
    metadata: dict[str, Any] = {}
    if po_number:
        metadata["po_number"] = po_number
    if customer_name_source:
        metadata["customer_name_source"] = customer_name_source

    return {
        "order_number": order_number,
        "customer_name": resolved_customer,
        "shipping_date": shipping,
        "delivery_date": delivery,
        "pickup_location_id": None,
        "delivery_location_id": None,
        "load_type": LoadType.LTL.value,
        "metadata": metadata,
    }


def projected_row_to_tender_product_insert(
    row: dict[str, Any],
    *,
    active_pack_code_index: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Build kwargs for ``TenderProductsRepository.insert_batch`` (excluding tenant/tender_id).

    Returns ``None`` when required product fields are missing or invalid.
    """
    order_number = identifier_string_from_cell(row.get("order_number")) or ""
    if not order_number:
        return None
    if parse_order_position(row.get("order_position")) is None:
        return None

    product_name = str(row.get("product_name") or "").strip()
    if not product_name:
        return None

    qty = _parse_order_quantity(row.get("order_quantity"))
    if qty is None:
        return None

    weight_unit = parse_weight_unit(row.get("weight_unit"))
    if weight_unit is None:
        return None

    pack_id = resolve_pack_code_id(
        row,
        active_pack_code_index=active_pack_code_index,
    )
    # VKPREIS: optional unit price; invalid/missing does not block ingest
    price_per_unit = _parse_order_quantity(row.get("price_per_unit"))

    return {
        "order_number": order_number,
        "product_name": product_name,
        "order_quantity": qty,
        "pack_code_id": pack_id,
        "price_per_unit": price_per_unit,
        "weight_unit": weight_unit,
        "metadata": {},
    }


def tender_product_line_key(
    product: dict[str, Any],
) -> tuple[str, Decimal, str | None]:
    """Stable key for de-duplicating product lines on re-import."""
    return (
        str(product["product_name"]),
        product["order_quantity"],
        product.get("pack_code_id"),
    )
