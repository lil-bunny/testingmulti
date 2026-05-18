"""Node: calculate Gelita tender params and enrich state."""

from __future__ import annotations

from decimal import Decimal

import app.configs.gelita_config as gelita_config
from app.models.load_type import LoadType
from app.services.tender_service import TenderService


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
        state.data["tender_calc_error"] = "missing_tenant_id"
        return state
    if not tender_id:
        state.data["tender_calc_error"] = "missing_tender_id"
        return state

    # TODO: confirm the value for this plus fetch from tenant config
    pallet_weight_lb = float(gelita_config.PALLET_WEIGHT_LBS)
    pallet_threshold = int(gelita_config.PALLET_THRESHOLD)

    tender_svc = TenderService()
    row = tender_svc.read_row(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not row:
        state.data["tender_calc_error"] = "tender_not_found"
        return state

    order_quantity = Decimal(str(row["order_quantity"]))
    qty_per_unit = row.get("qty_per_unit")
    total_qty = row.get("total_qty")

    if qty_per_unit is None or qty_per_unit == 0:
        state.data["tender_calc_error"] = "missing_qty_per_unit"
        return state
    if total_qty is None or total_qty == 0:
        state.data["tender_calc_error"] = "missing_total_qty"
        return state

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

    # TODO: map Customer PO column when product confirms source
    customer_po = "TBD"

    ship_date = row.get("shipping_date")
    ship_date_str = ship_date.isoformat() if hasattr(ship_date, "isoformat") else str(ship_date or "")

    state.data.update(
        {
            "order_number": row.get("order_number") or "",
            "pack_code": row.get("pack_code") or "",
            "customer_po": customer_po,
            "product_name": row.get("product_name") or "",
            "ship_date": ship_date_str,
            "pickup_address": row.get("pickup_address") or "",
            "delivery_address": row.get("delivery_address") or "",
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
