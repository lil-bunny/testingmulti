"""Node: calculate Gelita tender params and enrich state."""

from __future__ import annotations

from decimal import Decimal

from app.domain.delivery_address import format_usps_mailing_address
from app.domain.load_tendering_settings import action_settings
from app.models.load_type import LoadType
from app.services.tender_service import TenderService
from app.workflows.nodes.tender_calc_failure import record_tender_calc_failure


def _fail(state, error_code: str):
    state.data["tender_calc_error"] = error_code
    record_tender_calc_failure(state, error_code=error_code)
    return state


def calculate_tender_params(state):
    """
    Load tenant + tender, apply Gelita formulas, persist ``load_type``, enrich state.

    Per scoped TODO 3.1 (order quantity in **kg**):
    - ``pieces = order_quantity / qty_per_unit``
    - ``pallets = order_quantity / total_qty``
    - ``gross_weight = (order_quantity * 2.2) + (pallet_weight * pallets)`` (lbs)

    Pack sizing comes from ``TenderService.read_row`` (``pack_codes`` join + metadata fallback).
    """
    tenant_id = (state.tenant_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()

    if not tenant_id:
        return _fail(state, "missing_tenant_id")
    if not tender_id:
        return _fail(state, "missing_tender_id")

    cfg = action_settings(state, "tender_calculate")
    try:
        pallet_weight_lb = float(cfg["pallet_weight_lbs"])
    except (KeyError, TypeError, ValueError):
        return _fail(state, "missing_tenant_settings_pallet_weight_lbs")
    try:
        pallet_threshold = int(cfg["pallet_threshold"])
    except (KeyError, TypeError, ValueError):
        return _fail(state, "missing_tenant_settings_pallet_threshold")
    pickup_address = cfg.get("gelita_pickup_address")
    if not isinstance(pickup_address, dict):
        return _fail(state, "missing_tenant_settings_gelita_pickup_address")

    tender_svc = TenderService()
    row = tender_svc.read_row(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not row:
        return _fail(state, "tender_not_found")

    if not row.get("pack_code_id"):
        tender_row = state.data.get("tender_row")
        excel_pack = ""
        if isinstance(tender_row, dict):
            excel_pack = str(tender_row.get("pack_code") or "").strip()
        if excel_pack:
            state.data["pack_code"] = excel_pack
        return _fail(state, "missing_pack_code")

    order_quantity = Decimal(str(row["order_quantity"]))
    qty_per_unit = row.get("qty_per_unit")
    total_qty = row.get("total_qty")

    if qty_per_unit is None or qty_per_unit == 0:
        return _fail(state, "missing_qty_per_unit")
    if total_qty is None or total_qty == 0:
        return _fail(state, "missing_total_qty")

    qty_per_unit = Decimal(str(qty_per_unit))
    total_qty = Decimal(str(total_qty))

    pieces_dec = order_quantity / qty_per_unit
    pallets_dec = order_quantity / total_qty
    gross_weight_dec = (order_quantity * Decimal("2.2")) + (
        Decimal(str(pallet_weight_lb)) * pallets_dec
    )

    pallets_float = float(pallets_dec)
    load_type_enum = (
        LoadType.LTL if pallets_float <= float(pallet_threshold) else LoadType.FTL
    )

    tender_svc.update_load_type(
        tenant_id=tenant_id,
        tender_id=tender_id,
        load_type=load_type_enum,
    )

    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    customer_po = str(metadata.get("po_number") or "").strip()
    if not customer_po:
        tender_row = state.data.get("tender_row")
        if isinstance(tender_row, dict):
            customer_po = str(tender_row.get("po_number") or "").strip()
    if not customer_po:
        customer_po = "TBD"

    ship_date = row.get("shipping_date")
    ship_date_str = ship_date.isoformat() if hasattr(ship_date, "isoformat") else str(ship_date or "")

    delivery_date = row.get("delivery_date")
    delivery_date_str = (
        delivery_date.isoformat()
        if hasattr(delivery_date, "isoformat")
        else str(delivery_date or "")
    )

    order_value = ""
    if isinstance(metadata, dict):
        for key in ("value", "order_value", "shipment_value"):
            raw = metadata.get(key)
            if raw is not None and str(raw).strip():
                order_value = str(raw).strip()
                break

    pickup_formatted = format_usps_mailing_address(pickup_address)
    delivery_raw = row.get("delivery_address")
    delivery_formatted = (
        format_usps_mailing_address(delivery_raw)
        if isinstance(delivery_raw, dict)
        else ""
    )

    state.data.update(
        {
            "order_number": row.get("order_number") or "",
            "pack_code": row.get("pack_code") or "",
            "customer_po": customer_po,
            "product_name": row.get("product_name") or "",
            "ship_date": ship_date_str,
            "delivery_date": delivery_date_str,
            "order_value": order_value,
            "pickup_address": pickup_formatted,
            "delivery_address": delivery_formatted,
            "pieces_count": f"{pieces_dec:.2f}",
            "pallets_count": f"{pallets_dec:.2f}",
            "gross_weight_lbs": f"{gross_weight_dec:,.2f}",
            "pallet_weight_lb": pallet_weight_lb,
            "pallet_threshold": pallet_threshold,
            "load_type": load_type_enum.lower(),
            "qty_per_unit": str(qty_per_unit),
            "total_qty": str(total_qty),
            "pack_code_description": row.get("pack_code_description") or "",
            "units_per_pallet": (
                str(row["units_per_pallet"])
                if row.get("units_per_pallet") is not None
                else ""
            ),
            "unit_dims": row.get("unit_dims") or "",
            "pallet_dims": row.get("pallet_dims") or "",
            "pallet_type": row.get("pallet_type") or "",
        }
    )
    return state
