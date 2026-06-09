"""Node: calculate Gelita tender params and enrich state."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from typing import Any

from app.domain.delivery_address import format_usps_mailing_address
from app.domain.load_tendering_settings import (
    action_settings,
    load_type_from_pallet_totals,
)
from app.domain.load_tendering_state import get_tender, ingest_pack_code, set_tender
from app.domain.error_catalog import BusinessError, SystemError
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService
from app.workflows.utils.decorators import safe_node


def gelita_calculate_params(
    *,
    order_quantity,
    qty_per_unit,
    total_qty,
    pallet_weight_lb,
    unit_price,
):
    """
    Per-product Gelita formulas.

    Returns ``pieces_int``, ``pallets_int``, ``gross_weight_dec``, ``product_value``
    (``unit_price * order_quantity`` when unit price is present; else ``None``).
    Order load type is derived separately via ``load_type_from_pallet_totals``.
    """
    order_quantity = Decimal(str(order_quantity))
    qty_per_unit = Decimal(str(qty_per_unit))
    total_qty = Decimal(str(total_qty))

    pieces_raw = order_quantity / qty_per_unit
    pieces_int = int(pieces_raw.to_integral_value(rounding=ROUND_CEILING))
    pallets_raw = order_quantity / total_qty
    pallets_int = int(pallets_raw.to_integral_value(rounding=ROUND_CEILING))
    # pallets_dec = Decimal(pallets_int)

    gross_weight_dec = (order_quantity * Decimal("2.2")) + (
        Decimal(str(pallet_weight_lb)) * pallets_int
    )

    product_value: Decimal | None = None
    if unit_price is not None and unit_price != "":
        try:
            unit_price_dec = Decimal(str(unit_price))
            if unit_price_dec.is_finite():
                product_value = unit_price_dec * order_quantity
        except Exception:
            product_value = None

    return pieces_int, pallets_int, gross_weight_dec, product_value


@safe_node
def calculate_tender_params(state):
    """
    Load tenant + tender, apply Gelita formulas per product line, persist order ``load_type``.

    Writes ``state.data['tender']`` (order fields + ``tender_products`` with calc).
    """
    tenant_id = (state.tenant_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()

    if not tenant_id:
        raise WorkflowException(BusinessError.MISSING_TENANT_ID)
    if not tender_id:
        raise WorkflowException(BusinessError.MISSING_TENDER_ID)

    cfg = action_settings(state, "tender_calculate")
    try:
        pallet_weight_lb = float(cfg["pallet_weight_lbs"])
    except (KeyError, TypeError, ValueError):
        raise WorkflowException(SystemError.MISSING_TENANT_SETTINGS_PALLET_WEIGHT_LBS)
    try:
        pallet_threshold = int(cfg["pallet_threshold"])
    except (KeyError, TypeError, ValueError):
        raise WorkflowException(SystemError.MISSING_TENANT_SETTINGS_PALLET_THRESHOLD)
    pickup_address = cfg.get("gelita_pickup_address")
    if not isinstance(pickup_address, dict):
        raise WorkflowException(SystemError.MISSING_TENANT_SETTINGS_GELITA_PICKUP_ADDRESS)

    tender_service = TenderService()
    bundle = tender_service.read_order(
        tenant_id=tenant_id,
        tender_id=tender_id,
    )
    if not bundle:
        raise WorkflowException(BusinessError.TENDER_NOT_FOUND)

    tender = bundle["tender"]
    products = bundle["products"]
    if not products:
        raise WorkflowException(BusinessError.MISSING_PRODUCT_LINES)

    products_calc: list[dict[str, Any]] = []
    enriched_products: list[dict[str, Any]] = []
    total_pieces = Decimal(0)
    total_pallets = 0
    total_gross = Decimal(0)

    for product in products:
        if not product.get("pack_code_id"):
            excel_pack = ingest_pack_code(state.data)
            if excel_pack:
                existing = get_tender(state.data) or {}
                existing["pack_code"] = excel_pack
                set_tender(state.data, existing)
            raise WorkflowException(BusinessError.MISSING_PACK_CODE)

        order_quantity = product["order_quantity"]
        qty_per_unit = product.get("qty_per_unit")
        total_qty = product.get("total_qty")

        if qty_per_unit is None or qty_per_unit == 0:
            raise WorkflowException(BusinessError.MISSING_QTY_PER_UNIT)
        if total_qty is None or total_qty == 0:
            raise WorkflowException(BusinessError.MISSING_TOTAL_QTY)

        pieces_int, pallets_int, gross_weight_dec, product_value = gelita_calculate_params(
            order_quantity=order_quantity,
            qty_per_unit=qty_per_unit,
            total_qty=total_qty,
            pallet_weight_lb=pallet_weight_lb,
            unit_price=product.get("price_per_unit"),
        )

        products_calc.append({"pallets_count": pallets_int})
        total_pieces += pieces_int
        total_pallets += pallets_int
        total_gross += gross_weight_dec

        qty_per_unit_dec = Decimal(str(qty_per_unit))
        total_qty_dec = Decimal(str(total_qty))
        enriched: dict[str, Any] = {
            **product,
            "pieces_count": str(pieces_int),
            "pallets_count": str(pallets_int),
            "gross_weight_lbs": f"{gross_weight_dec:,.2f}",
            "qty_per_unit": str(qty_per_unit_dec),
            "total_qty": str(total_qty_dec),
            "product_value": product_value,
        }
        enriched_products.append(enriched)

    load_type = load_type_from_pallet_totals(
        products_calc,
        pallet_threshold=pallet_threshold,
    )

    tender_service.update_load_type(
        tenant_id=tenant_id,
        tender_id=tender_id,
        load_type=load_type,
    )

    metadata = tender.get("metadata") if isinstance(tender.get("metadata"), dict) else {}
    customer_po = str(metadata.get("po_number") or "").strip()
    if not customer_po:
        prior = get_tender(state.data) or {}
        customer_po = str(prior.get("customer_po") or prior.get("po_number") or "").strip()
    if not customer_po:
        raise WorkflowException(BusinessError.MISSING_CUSTOMER_PO)

    ship_date = tender.get("shipping_date")
    ship_date_str = ship_date.isoformat() if hasattr(ship_date, "isoformat") else str(ship_date or "")

    delivery_date = tender.get("delivery_date")
    delivery_date_str = (
        delivery_date.isoformat()
        if hasattr(delivery_date, "isoformat")
        else str(delivery_date or "")
    )

    # order_value = ""
    # if isinstance(metadata, dict):
    #     for key in ("value", "order_value", "shipment_value"):
    #         raw = metadata.get(key)
    #         if raw is not None and str(raw).strip():
    #             order_value = str(raw).strip()
    #             break

    pickup_formatted = format_usps_mailing_address(pickup_address)
    delivery_raw = tender.get("delivery_address")
    delivery_formatted = (
        format_usps_mailing_address(delivery_raw)
        if isinstance(delivery_raw, dict)
        else ""
    )

    prior_tender = get_tender(state.data) or {}
    set_tender(
        state.data,
        {
            **prior_tender,
            "order_number": tender.get("order_number")
            or prior_tender.get("order_number")
            or "",
            "customer_name": tender.get("customer_name")
            or prior_tender.get("customer_name")
            or "",
            "customer_po": customer_po,
            "ship_date": ship_date_str,
            "delivery_date": delivery_date_str,
            # "order_value": order_value,
            "pickup_address": pickup_formatted,
            "delivery_address": delivery_formatted,
            # "pieces_count": f"{total_pieces:.2f}",
            # "pallets_count": str(total_pallets),
            # "gross_weight_lbs": f"{total_gross:,.2f}",
            # "pallet_weight_lb": pallet_weight_lb,
            "pallet_threshold": pallet_threshold,
            "load_type": load_type.lower(),
            "tender_products": enriched_products,
        },
    )
    return state
