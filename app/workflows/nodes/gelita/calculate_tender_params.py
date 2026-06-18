"""Node: calculate Gelita tender params and enrich state."""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any

from app.domain.delivery_address import (
    format_usps_mailing_address,
    is_unresolved_customer_name,
)
from app.models.weight_unit import WeightUnit
from app.domain.load_tendering_settings import (
    gelita_tender_calculate_settings,
    load_type_from_pallet_totals,
)
from app.domain.load_tendering_state import (
    get_tender,
    get_tender_products,
    ingest_delivery_address_code,
    ingest_pack_code,
    set_tender,
)
from app.domain.error_catalog import BusinessError, SystemError, format_error_message
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.exceptions import WorkflowException
from app.services.tender_service import TenderService
from app.workflows.utils.decorators import safe_node
from app.workflows.utils.gelita_soft_fail import record_business_gap, record_business_gap_or_raise

_PALLET_ROUND_TOLERANCE = Decimal("0.05")
_KG_TO_LBS = Decimal("2.2046")


def _pack_code_for_error(product: dict[str, Any], state_data: dict[str, Any]) -> str:
    code = str(product.get("pack_code") or "").strip()
    if code:
        return code
    return ingest_pack_code(state_data)


def _product_weight_lbs(order_quantity: Decimal, weight_unit: WeightUnit) -> Decimal:
    if weight_unit is WeightUnit.LBS:
        return order_quantity
    return order_quantity * _KG_TO_LBS


def _round_pallet_count(pallets_raw: Decimal) -> int:
    """
    QA pallet rounding: if fractional part is <= 0.05, round down; else round up.

    Examples: 3.04 -> 3, 3.05 -> 3, 3.06 -> 4.
    """
    floor_val = int(pallets_raw.to_integral_value(rounding=ROUND_FLOOR))
    if pallets_raw - Decimal(floor_val) <= _PALLET_ROUND_TOLERANCE:
        return floor_val
    return floor_val + 1


def _enriched_product_without_calc(product: dict[str, Any]) -> dict[str, Any]:
    """Placeholder product line when calc inputs are missing under soft-fail."""
    return {
        **product,
        "pieces_count": "",
        "pallets_count": "",
        "gross_weight_lbs": "",
        "product_value": None,
    }


def _product_gap_or_raise(
    state_data: dict[str, Any],
    error: BusinessError,
    **format_kwargs: str,
) -> bool:
    """Soft-record the gap when enabled; otherwise raise. Returns True when recorded."""
    if record_business_gap(state_data, error, **format_kwargs):
        return True
    raise WorkflowException(error, format_error_message(error, **format_kwargs))


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

    pieces_raw = order_quantity / qty_per_unit
    pieces_int = int(pieces_raw.to_integral_value(rounding=ROUND_CEILING))
    pallets_raw = order_quantity / total_qty
    pallets_int = _round_pallet_count(pallets_raw)

    unit = WeightUnit.parse(weight_unit) or WeightUnit.KG
    gross_weight_raw = _product_weight_lbs(order_quantity, unit) + (
        Decimal(str(pallet_weight_lb)) * pallets_int
    )
    gross_weight_dec = Decimal(
        int(gross_weight_raw.to_integral_value(rounding=ROUND_CEILING))
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
        delivery_code = ingest_delivery_address_code(state.data)
        if delivery_code:
            existing = get_tender(state.data) or {}
            existing["delivery_address_code"] = delivery_code
            set_tender(state.data, existing)
            state.data["delivery_address_code"] = delivery_code
        record_business_gap_or_raise(
            state.data,
            BusinessError.MISSING_DELIVERY_ADDRESS,
            del_code=delivery_code,
        )

    if is_unresolved_customer_name(tender):
        delivery_code = ingest_delivery_address_code(state.data)
        if delivery_code:
            existing = get_tender(state.data) or {}
            existing["delivery_address_code"] = delivery_code
            set_tender(state.data, existing)
            state.data["delivery_address_code"] = delivery_code
        record_business_gap_or_raise(
            state.data,
            BusinessError.MISSING_CUSTOMER_NAME,
            del_code=delivery_code,
        )

    products_calc: list[dict[str, Any]] = []
    enriched_products: list[dict[str, Any]] = []
    total_gross = Decimal(0)

    for product in products:
        if not product.get("pack_code_id"):
            excel_pack = ingest_pack_code(state.data)
            if excel_pack:
                existing = get_tender(state.data) or {}
                existing["pack_code"] = excel_pack
                set_tender(state.data, existing)
                state.data["pack_code"] = excel_pack
            if _product_gap_or_raise(
                state.data,
                BusinessError.MISSING_PACK_CODE,
                pack_code=excel_pack,
            ):
                enriched_products.append(_enriched_product_without_calc(product))
                continue

        order_quantity = product["order_quantity"]
        qty_per_unit = product.get("qty_per_unit")
        total_qty = product.get("total_qty")
        pack_code = _pack_code_for_error(product, state.data)
        unit_dims = product.get("unit_dims")

        product_gap = False
        if qty_per_unit is None or qty_per_unit == 0:
            product_gap |= _product_gap_or_raise(
                state.data,
                BusinessError.MISSING_QTY_PER_UNIT,
                pack_code=pack_code,
            )
        if total_qty is None or total_qty == 0:
            product_gap |= _product_gap_or_raise(
                state.data,
                BusinessError.MISSING_TOTAL_QTY,
                pack_code=pack_code,
            )
        if unit_dims is None or not str(unit_dims).strip():
            product_gap |= _product_gap_or_raise(
                state.data,
                BusinessError.MISSING_UNIT_DIMS,
                pack_code=pack_code,
            )

        if product_gap:
            enriched_products.append(_enriched_product_without_calc(product))
            continue

        profile_key, pallet_profile = calc_settings.resolve_pallet_type(
            product.get("pallet_type")
        )

        pieces_int, pallets_int, gross_weight_dec, product_value = gelita_calculate_params(
            order_quantity=order_quantity,
            qty_per_unit=qty_per_unit,
            total_qty=total_qty,
            pallet_weight_lb=pallet_profile.weight_lbs,
            unit_price=product.get("price_per_unit"),
            weight_unit=product.get("weight_unit"),
        )

        products_calc.append(
            {
                "pallets_count": pallets_int,
                "pallet_profile": profile_key,
                "pallet_threshold": pallet_profile.threshold,
            }
        )
        total_gross += gross_weight_dec

        qty_per_unit_dec = Decimal(str(qty_per_unit))
        total_qty_dec = Decimal(str(total_qty))
        enriched_products.append(
            {
                **product,
                "pieces_count": str(pieces_int),
                "pallets_count": str(pallets_int),
                "gross_weight_lbs": f"{int(gross_weight_dec):,}",
                "qty_per_unit": str(qty_per_unit_dec),
                "total_qty": str(total_qty_dec),
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
