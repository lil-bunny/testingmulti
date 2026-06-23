"""Node: calculate Gelita tender params and enrich state."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from app.domain.delivery_address import (
    format_usps_mailing_address,
    is_unresolved_customer_name,
)
from app.models.weight_unit import WeightUnit
from app.domain.ingest_source_fields import (
    delivery_gap_context,
    pack_code_for_product_gap,
    product_gap_context,
    product_or_catalog_gap_context,
)
from app.domain.load_tendering_settings import (
    gelita_tender_calculate_settings,
    load_type_from_pallet_totals,
)
from app.domain.load_tendering_state import (
    get_tender,
    get_tender_products,
    set_tender,
)
from app.domain.error_catalog import BusinessError, SystemError
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService
from app.workflows.utils.decorators import safe_node
from app.workflows.utils.gelita_soft_fail import record_business_gap_or_raise

_PALLET_ROUND_TOLERANCE = Decimal("0.05")
_KG_TO_LBS = Decimal("2.2046")


def _sync_delivery_address_code(state_data: dict[str, Any], tender: dict[str, Any]) -> None:
    delivery_code = delivery_gap_context(tender, state_data).get("del_code", "")
    if not delivery_code:
        return
    existing = get_tender(state_data) or {}
    existing["delivery_address_code"] = delivery_code
    set_tender(state_data, existing)
    state_data["delivery_address_code"] = delivery_code


def _product_weight_lbs(order_quantity: Decimal, weight_unit: WeightUnit) -> Decimal:
    if weight_unit is WeightUnit.LBS:
        return order_quantity
    return order_quantity * _KG_TO_LBS


def _pieces_count(order_quantity: Decimal, qty_per_unit: Decimal) -> int:
    pieces_raw = order_quantity / qty_per_unit
    return int(pieces_raw.to_integral_value(rounding=ROUND_CEILING))


def _pallets_count(order_quantity: Decimal, total_qty: Decimal) -> int:
    pallets_raw = order_quantity / total_qty
    return _round_pallet_count(pallets_raw)


def _gross_weight_lbs(
    *,
    order_quantity: Decimal,
    pallets_count: int,
    pallet_weight_lb: Decimal,
    weight_unit: WeightUnit | str | None,
) -> Decimal:
    unit = WeightUnit.parse(weight_unit) or WeightUnit.KG
    gross_weight_raw = _product_weight_lbs(order_quantity, unit) + (
        pallet_weight_lb * pallets_count
    )
    return Decimal(int(gross_weight_raw.to_integral_value(rounding=ROUND_CEILING)))


def _product_value(
    *,
    order_quantity: Decimal,
    unit_price: Decimal | str | None,
) -> Decimal | None:
    if unit_price is None or unit_price == "":
        return None
    try:
        unit_price_dec = Decimal(str(unit_price))
        if unit_price_dec.is_finite():
            return unit_price_dec * order_quantity
    except Exception:
        return None
    return None


def _round_pallet_count(pallets_raw: Decimal) -> int:
    """
    QA pallet rounding: if fractional part is <= 0.05, round down; else round up.

    Examples: 3.04 -> 3, 3.05 -> 3, 3.06 -> 4.
    """
    floor_val = int(pallets_raw.to_integral_value(rounding=ROUND_FLOOR))
    if pallets_raw - Decimal(floor_val) <= _PALLET_ROUND_TOLERANCE:
        return floor_val
    return floor_val + 1


def gelita_calculate_params(
    *,
    order_quantity,
    qty_per_unit,
    total_qty,
    pallet_weight_lb,
    unit_price,
    weight_unit: WeightUnit | str | None = None,
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
    pieces_int = _pieces_count(order_quantity, qty_per_unit)
    pallets_int = _pallets_count(order_quantity, total_qty)
    gross_weight_dec = _gross_weight_lbs(
        order_quantity=order_quantity,
        pallets_count=pallets_int,
        pallet_weight_lb=Decimal(str(pallet_weight_lb)),
        weight_unit=weight_unit,
    )
    product_value = _product_value(order_quantity=order_quantity, unit_price=unit_price)
    return pieces_int, pallets_int, gross_weight_dec, product_value


@safe_node
def calculate_tender_params(state):
    """Apply Gelita formulas per hydrated product line and persist order load_type."""
    tenant_id = (state.tenant_id or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()

    if not tenant_id:
        raise WorkflowException(BusinessError.MISSING_TENANT_ID)
    if not tender_id:
        raise WorkflowException(BusinessError.MISSING_TENDER_ID)

    calc_settings = gelita_tender_calculate_settings(state)
    if calc_settings is None:
        raise WorkflowException(SystemError.MISSING_TENANT_SETTINGS_PALLET_PROFILES)
    pickup_address = calc_settings.gelita_pickup_address.model_dump()

    tender = get_tender(state.data)
    if not tender:
        raise WorkflowException(BusinessError.TENDER_NOT_FOUND)

    products = get_tender_products(tender)
    if not products:
        raise WorkflowException(BusinessError.MISSING_PRODUCT_LINES)

    tender_service = TenderService()

    delivery_raw = tender.get("delivery_address")
    if delivery_raw is None or not isinstance(delivery_raw, dict):
        _sync_delivery_address_code(state.data, tender)
        record_business_gap_or_raise(
            state.data,
            BusinessError.MISSING_DELIVERY_ADDRESS,
            **delivery_gap_context(tender, state.data),
        )

    if is_unresolved_customer_name(tender):
        _sync_delivery_address_code(state.data, tender)
        record_business_gap_or_raise(
            state.data,
            BusinessError.MISSING_CUSTOMER_NAME,
            **delivery_gap_context(tender, state.data),
        )

    products_calc: list[dict[str, Any]] = []
    enriched_products: list[dict[str, Any]] = []
    total_gross = Decimal(0)
    multi_product = len(products) > 1

    for product in products:
        if not product.get("pack_code_id"):
            record_business_gap_or_raise(
                state.data,
                BusinessError.MISSING_PACK_CODE,
                **product_gap_context(product),
            )

        order_quantity = product["order_quantity"]
        qty_per_unit = product.get("qty_per_unit")
        total_qty = product.get("total_qty")
        pack_code = pack_code_for_product_gap(product)
        unit_dims = product.get("unit_dims")
        gap_context, catalog_gap = product_or_catalog_gap_context(
            product, pack_code=pack_code
        )

        profile_key, pallet_profile = calc_settings.resolve_pallet_type(
            product.get("pallet_type")
        )
        pieces_int: int | None = None
        pallets_int: int | None = None
        gross_weight_dec: Decimal | None = None

        if qty_per_unit is None or qty_per_unit == 0:
            record_business_gap_or_raise(
                state.data,
                BusinessError.MISSING_QTY_PER_UNIT,
                multi_product=multi_product,
                catalog_gap=catalog_gap,
                **gap_context,
            )
        else:
            pieces_int = _pieces_count(
                Decimal(str(order_quantity)),
                Decimal(str(qty_per_unit)),
            )

        if total_qty is None or total_qty == 0:
            record_business_gap_or_raise(
                state.data,
                BusinessError.MISSING_TOTAL_QTY,
                multi_product=multi_product,
                catalog_gap=catalog_gap,
                **gap_context,
            )
        else:
            pallets_int = _pallets_count(
                Decimal(str(order_quantity)),
                Decimal(str(total_qty)),
            )
            gross_weight_dec = _gross_weight_lbs(
                order_quantity=Decimal(str(order_quantity)),
                pallets_count=pallets_int,
                pallet_weight_lb=Decimal(str(pallet_profile.weight_lbs)),
                weight_unit=product.get("weight_unit"),
            )

        if unit_dims is None or not str(unit_dims).strip():
            record_business_gap_or_raise(
                state.data,
                BusinessError.MISSING_UNIT_DIMS,
                multi_product=multi_product,
                catalog_gap=catalog_gap,
                **gap_context,
            )

        product_value = _product_value(
            order_quantity=Decimal(str(order_quantity)),
            unit_price=product.get("price_per_unit"),
        )

        products_calc.append(
            {
                "pallets_count": pallets_int if pallets_int is not None else "",
                "pallet_profile": profile_key,
                "pallet_threshold": pallet_profile.threshold,
            }
        )
        if gross_weight_dec is not None:
            total_gross += gross_weight_dec

        enriched_products.append(
            {
                **product,
                "pieces_count": str(pieces_int) if pieces_int is not None else "",
                "pallets_count": str(pallets_int) if pallets_int is not None else "",
                "gross_weight_lbs": f"{int(gross_weight_dec):,}"
                if gross_weight_dec is not None
                else "",
                "qty_per_unit": str(qty_per_unit)
                if qty_per_unit is not None and qty_per_unit != ""
                else "",
                "total_qty": str(total_qty)
                if total_qty is not None and total_qty != ""
                else "",
                "product_value": product_value,
            }
        )

    total_pallets = sum(
        int(item["pallets_count"])
        for item in products_calc
        if str(item.get("pallets_count") or "").isdigit()
    )

    load_type = load_type_from_pallet_totals(products_calc)

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
        record_business_gap_or_raise(state.data, BusinessError.MISSING_CUSTOMER_PO)

    ship_date = parse_tender_date(tender.get("shipping_date"))
    ship_date_str = ship_date.isoformat() if ship_date else ""

    delivery_date = parse_tender_date(tender.get("delivery_date"))
    delivery_date_str = delivery_date.isoformat() if delivery_date else ""

    pickup_formatted = format_usps_mailing_address(pickup_address)
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
            "pickup_address": pickup_formatted,
            "delivery_address": delivery_formatted,
            "pallets_count": str(total_pallets),
            "gross_weight_lbs": f"{int(total_gross):,}" if total_gross else "",
            "load_type": load_type.lower(),
            "tender_products": enriched_products,
        },
    )
    return state
