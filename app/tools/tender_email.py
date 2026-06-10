"""Build load-tender email bodies from tenant HTML templates (order + product lines)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal
from html import escape
from typing import Any

from app.models.weight_unit import WeightUnit

__all__ = [
    "TenderEmailBuildInput",
    "build_tender_email_input_from_tender",
    "format_tender_email_subject",
    "build_ltl_tender_email_from_tender",
    "build_ftl_tender_email_from_tender",
]


@dataclass(frozen=True)
class TenderEmailProductLine:
    """One ``tender_products`` row after calc (from workflow state or ``read_order``)."""

    product_name: str
    pack_code: str
    pieces_count: str
    qty_per_unit: str
    weight_unit: str
    pallets_count: str
    pallet_dims: str
    gross_weight_lbs: str
    price: str


@dataclass(frozen=True)
class TenderEmailBuildInput:
    """Order-level tender email context (tenant-agnostic)."""

    order_number: str
    customer_po: str
    ship_date: str
    delivery_date: str
    order_value: str
    pickup_address: str
    delivery_address: str
    pieces_count: str
    pallets_count: str
    gross_weight_lbs: str
    products: tuple[TenderEmailProductLine, ...]


def _format_price(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        return f"{Decimal(str(value)):,.2f}"
    except Exception:
        return escape(str(value).strip())


def _html_address_block(text: str) -> str:
    if not text:
        return ""
    return "<br />".join(
        escape(line.strip()) for line in str(text).splitlines() if line.strip()
    )


def _str_field(data: dict[str, Any], key: str) -> str:
    raw = data.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def _product_lines_from_payload(
    tender_data: dict[str, Any],
    calculated: dict[str, Any],
) -> tuple[TenderEmailProductLine, ...]:
    raw = tender_data.get("tender_products")
    if not isinstance(raw, list) or not raw:
        raw = calculated.get("tender_products")
    if not isinstance(raw, list):
        return ()

    lines: list[TenderEmailProductLine] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        lines.append(
            TenderEmailProductLine(
                product_name=_str_field(row, "product_name"),
                pack_code=_str_field(row, "pack_code"),
                pieces_count=_str_field(row, "pieces_count"),
                qty_per_unit=_str_field(row, "qty_per_unit"),
                weight_unit=_str_field(row, "weight_unit") or WeightUnit.KG.value,
                pallets_count=_str_field(row, "pallets_count"),
                pallet_dims=_str_field(row, "pallet_dims"),
                gross_weight_lbs=_str_field(row, "gross_weight_lbs"),
                price=_format_price(row.get("product_value")),
            )
        )
    return tuple(lines)


def build_tender_email_input_from_tender(tender: dict[str, Any]) -> TenderEmailBuildInput:
    """Normalize ``state.data['tender']`` for email builders."""
    products = _product_lines_from_payload(tender, tender)
    pieces = _str_field(tender, "pieces_count")
    pallets = _str_field(tender, "pallets_count")
    gross = _str_field(tender, "gross_weight_lbs")
    order_value = _str_field(tender, "order_value")
    if not pieces and products:
        pieces = products[0].pieces_count
    if not pallets and products:
        pallets = products[0].pallets_count
    if not gross and products:
        gross = _sum_product_field(products, "gross_weight_lbs")
    if not order_value and products:
        order_value = _sum_product_field(products, "price", money=True)
    return TenderEmailBuildInput(
        order_number=_str_field(tender, "order_number"),
        customer_po=_str_field(tender, "customer_po"),
        ship_date=_str_field(tender, "ship_date"),
        delivery_date=_str_field(tender, "delivery_date"),
        order_value=order_value,
        pickup_address=_html_address_block(tender.get("pickup_address") or ""),
        delivery_address=_html_address_block(tender.get("delivery_address") or ""),
        pieces_count=pieces,
        pallets_count=pallets,
        gross_weight_lbs=gross,
        products=products,
    )


def build_tender_email_input(
    tender_data: dict[str, Any],
    calculated: dict[str, Any],
) -> TenderEmailBuildInput:
    """Legacy: merge split tender + calculated dicts (tests). Prefer ``from_tender``."""
    merged = {**calculated, **tender_data, "tender_products": tender_data.get("tender_products") or calculated.get("tender_products")}
    return build_tender_email_input_from_tender(merged)


def _parse_numeric_field(value: str) -> Decimal | None:
    if not value:
        return None
    try:
        cleaned = value.strip().replace(",", "").removeprefix("~")
        return Decimal(cleaned)
    except Exception:
        return None


def _sum_product_field(
    products: tuple[TenderEmailProductLine, ...],
    field: str,
    *,
    money: bool = False,
) -> str:
    total = Decimal("0")
    found = False
    for line in products:
        raw = getattr(line, field)
        if not raw:
            continue
        parsed = _parse_numeric_field(raw)
        if parsed is None:
            return str(raw).strip()
        total += parsed
        found = True
    if not found:
        return ""
    if money:
        return f"{total:,.2f}"
    if total == total.to_integral_value():
        return str(int(total))
    return f"{total.normalize():f}"


def _ceil_weight_display(value: str) -> str:
    weight = value.strip()
    if not weight:
        return ""
    parsed = _parse_numeric_field(weight)
    if parsed is None:
        return weight
    ceiled = int(parsed.to_integral_value(rounding=ROUND_CEILING))
    return f"{ceiled:,}"


def _format_gross_weight_lbs(value: str) -> str:
    weight = _ceil_weight_display(value)
    if not weight:
        return ""
    return f"Gross weight: ~{weight} pounds"


def _format_order_value(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""
    parsed = _parse_numeric_field(raw)
    if parsed is not None:
        return f"Value: {parsed:,.2f}"
    return f"Value: {escape(raw)}"


def _combined_order_value_line(
    products: tuple[TenderEmailProductLine, ...],
    *,
    order_value: str = "",
) -> str:
    """Order-level shipment value (summed across all product lines)."""
    value = order_value.strip() or _sum_product_field(products, "price", money=True)
    return _format_order_value(value)


def _format_bags_line(line: TenderEmailProductLine) -> str:
    if not line.pieces_count:
        return ""
    unit = WeightUnit.parse(line.weight_unit) or WeightUnit.KG
    qty_raw = line.qty_per_unit.strip()
    if not qty_raw:
        return f"Pieces: {line.pieces_count} bags"
    try:
        qty_dec = Decimal(qty_raw.replace(",", ""))
        qty_str = (
            str(int(qty_dec))
            if qty_dec == qty_dec.to_integral_value()
            else f"{qty_dec.normalize():f}"
        )
    except Exception:
        qty_str = qty_raw
    return f"Pieces: {line.pieces_count} bags @ {qty_str}{unit.value} each"


def _format_pallets_line(line: TenderEmailProductLine) -> str:
    if not line.pallets_count:
        return ""
    count = line.pallets_count.strip()
    dims = line.pallet_dims.strip()
    if dims:
        return f"Number of pallets: {count} pallets ~ {escape(dims)}"
    return f"Number of pallets: {count}"


def _combined_gross_weight_line(
    products: tuple[TenderEmailProductLine, ...],
    *,
    order_gross_weight_lbs: str = "",
) -> str:
    """Order-level gross weight (summed across all product lines)."""
    gross = order_gross_weight_lbs.strip() or _sum_product_field(
        products, "gross_weight_lbs"
    )
    return _format_gross_weight_lbs(gross)


def _product_block_lines(
    line: TenderEmailProductLine,
    *,
    include_value: bool,
) -> str:
    """One product section for ``{products_block}`` (pieces/pallets per line)."""
    rows: list[str] = []
    bags_line = _format_bags_line(line)
    if bags_line:
        rows.append(bags_line)
    pallets_line = _format_pallets_line(line)
    if pallets_line:
        rows.append(pallets_line)
    if line.product_name:
        rows.append(f"Product: {escape(line.product_name)}")
    if include_value and line.price:
        rows.append(f"Value: {line.price}")
    return "<br />".join(rows)


def _combine_product_lines(
    products: tuple[TenderEmailProductLine, ...],
) -> tuple[TenderEmailProductLine, ...]:
    def sum_field(
        lines: list[TenderEmailProductLine],
        field: str,
        *,
        money: bool = False,
    ) -> str:
        summed = _sum_product_field(tuple(lines), field, money=money)
        if summed:
            return summed
        return getattr(lines[0], field)

    combined: list[TenderEmailProductLine] = []
    groups: dict[str, list[TenderEmailProductLine]] = {}
    positions: dict[str, int] = {}

    for line in products:
        key = line.product_name.strip()
        if not key:
            combined.append(line)
            continue
        if key not in groups:
            groups[key] = [line]
            positions[key] = len(combined)
            combined.append(line)
            continue

        groups[key].append(line)
        first = groups[key][0]
        combined[positions[key]] = TenderEmailProductLine(
            product_name=first.product_name,
            pack_code=first.pack_code,
            pieces_count=sum_field(groups[key], "pieces_count"),
            qty_per_unit=first.qty_per_unit,
            weight_unit=first.weight_unit,
            pallets_count=sum_field(groups[key], "pallets_count"),
            pallet_dims=first.pallet_dims,
            gross_weight_lbs=sum_field(groups[key], "gross_weight_lbs"),
            price=sum_field(groups[key], "price", money=True),
        )

    return tuple(combined)


def _products_block(
    products: tuple[TenderEmailProductLine, ...],
    *,
    include_value: bool,
    order_gross_weight_lbs: str = "",
    order_value: str = "",
    include_order_value: bool = False,
) -> str:
    summary_parts: list[str] = []
    gross_line = _combined_gross_weight_line(
        products,
        order_gross_weight_lbs=order_gross_weight_lbs,
    )
    if gross_line:
        summary_parts.append(gross_line)
    if include_order_value:
        value_line = _combined_order_value_line(
            products,
            order_value=order_value,
        )
        if value_line:
            summary_parts.append(value_line)
    summary = "<br />".join(summary_parts)
    per_line_value = include_value and not include_order_value

    if not products:
        return summary

    combined_products = _combine_product_lines(products)
    blocks: list[str] = []
    for line in combined_products:
        part = _product_block_lines(
            line,
            include_value=per_line_value,
        )
        if part:
            blocks.append(part)
    product_lines = "<br /><br />".join(blocks)
    if summary and product_lines:
        return f"{summary}<br /><br />{product_lines}"
    return summary or product_lines


def _ltl_products_block(
    products: tuple[TenderEmailProductLine, ...],
    *,
    order_gross_weight_lbs: str = "",
) -> str:
    """LTL: combined gross weight plus product, pieces, and pallets per line."""
    return _products_block(
        products,
        include_value=False,
        order_gross_weight_lbs=order_gross_weight_lbs,
    )


def _ftl_products_block(
    products: tuple[TenderEmailProductLine, ...],
    *,
    order_gross_weight_lbs: str = "",
    order_value: str = "",
) -> str:
    """FTL: combined gross weight and value plus product, pieces, and pallets per line."""
    return _products_block(
        products,
        include_value=False,
        include_order_value=True,
        order_gross_weight_lbs=order_gross_weight_lbs,
        order_value=order_value,
    )


def format_tender_email_subject(subject_template: str, ctx: TenderEmailBuildInput) -> str:
    """Fill tenant ``email_subject`` from tender order context."""
    data = {
        "order_number": ctx.order_number,
        "customer_po": ctx.customer_po,
        "po_number": ctx.customer_po,
    }
    return subject_template.format(**data)


def build_ltl_tender_email_from_tender(
    tender: dict[str, Any],
    template: str,
    subject_template: str,
) -> dict[str, str]:
    """Fill LTL template from ``state.data['tender']``."""
    ctx = build_tender_email_input_from_tender(tender)
    products_block = _ltl_products_block(
        ctx.products,
        order_gross_weight_lbs=ctx.gross_weight_lbs,
    )

    body_html = template.format(
        order_number=ctx.order_number,
        customer_po=ctx.customer_po,
        ship_date=ctx.ship_date,
        pickup_address=ctx.pickup_address,
        delivery_address=ctx.delivery_address,
        products_block=products_block,
    )

    subject = format_tender_email_subject(subject_template, ctx)
    return {"subject": subject, "body_html": body_html}


def build_ftl_tender_email_from_tender(
    tender: dict[str, Any],
    template: str,
    subject_template: str,
) -> dict[str, str]:
    """Fill FTL template from ``state.data['tender']``."""
    ctx = build_tender_email_input_from_tender(tender)
    products_block = _ftl_products_block(
        ctx.products,
        order_gross_weight_lbs=ctx.gross_weight_lbs,
        order_value=ctx.order_value,
    )

    body_html = template.format(
        order_number=ctx.order_number,
        customer_po=ctx.customer_po,
        ship_date=ctx.ship_date,
        delivery_date=ctx.delivery_date,
        delivery_address=ctx.delivery_address,
        products_block=products_block,
    )

    subject = format_tender_email_subject(subject_template, ctx)
    return {"subject": subject, "body_html": body_html}
