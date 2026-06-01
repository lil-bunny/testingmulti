"""Build load-tender email bodies from tenant HTML templates (order + product lines)."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from html import escape
from typing import Any

__all__ = [
    "TenderEmailBuildInput",
    "build_tender_email_input_from_tender",
    "build_ltl_tender_email_from_tender",
    "build_ftl_tender_email_from_tender",
]


@dataclass(frozen=True)
class TenderEmailProductLine:
    """One ``tender_products`` row after calc (from workflow state or ``read_order``)."""

    product_name: str
    pack_code: str
    pieces_count: str
    pallets_count: str
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
                pallets_count=_str_field(row, "pallets_count"),
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
    if not pieces and products:
        pieces = products[0].pieces_count
    if not pallets and products:
        pallets = products[0].pallets_count
    if not gross and products:
        gross = products[0].gross_weight_lbs
    return TenderEmailBuildInput(
        order_number=_str_field(tender, "order_number"),
        customer_po=_str_field(tender, "customer_po"),
        ship_date=_str_field(tender, "ship_date"),
        delivery_date=_str_field(tender, "delivery_date"),
        order_value=_str_field(tender, "order_value"),
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


def _product_block_lines(
    line: TenderEmailProductLine,
    *,
    include_gross: bool,
    include_value: bool,
) -> str:
    """One product section for ``{products_block}`` (pieces/pallets per line)."""
    rows: list[str] = []
    if line.product_name:
        rows.append(f"Product: {escape(line.product_name)}")
    if line.pieces_count:
        rows.append(f"Pieces: {line.pieces_count}")
    if line.pallets_count:
        rows.append(f"Number of pallets: {line.pallets_count}")
    if include_gross and line.gross_weight_lbs:
        rows.append(f"Gross weight: ~{line.gross_weight_lbs}")
    if include_value and line.price:
        rows.append(f"Value: {line.price}")
    return "<br />".join(rows)


def _combine_product_lines(
    products: tuple[TenderEmailProductLine, ...],
) -> tuple[TenderEmailProductLine, ...]:
    def parse_number(value: str) -> Decimal | None:
        if not value:
            return None
        try:
            cleaned = value.strip().replace(",", "").removeprefix("~")
            return Decimal(cleaned)
        except Exception:
            return None

    def sum_field(
        lines: list[TenderEmailProductLine],
        field: str,
        *,
        money: bool = False,
    ) -> str:
        total = Decimal("0")
        found = False
        for line in lines:
            raw = getattr(line, field)
            if not raw:
                continue
            parsed = parse_number(raw)
            if parsed is None:
                return getattr(lines[0], field)
            total += parsed
            found = True
        if not found:
            return getattr(lines[0], field)
        if money:
            return f"{total:,.2f}"
        if total == total.to_integral_value():
            return str(int(total))
        return f"{total.normalize():f}"

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
            pallets_count=sum_field(groups[key], "pallets_count"),
            gross_weight_lbs=sum_field(groups[key], "gross_weight_lbs", money=True),
            price=sum_field(groups[key], "price", money=True),
        )

    return tuple(combined)


def _products_block(
    products: tuple[TenderEmailProductLine, ...],
    *,
    include_gross: bool,
    include_value: bool,
) -> str:
    if not products:
        return ""
    products = _combine_product_lines(products)
    blocks: list[str] = []
    for line in products:
        part = _product_block_lines(
            line,
            include_gross=include_gross,
            include_value=include_value,
        )
        if part:
            blocks.append(part)
    return "<br /><br />".join(blocks)


def _ltl_products_block(products: tuple[TenderEmailProductLine, ...]) -> str:
    """LTL: product, pieces, pallets, and gross weight per line."""
    return _products_block(products, include_gross=True, include_value=False)


def _ftl_products_block(products: tuple[TenderEmailProductLine, ...]) -> str:
    """FTL: product, pieces, pallets, and optional per-line value."""
    return _products_block(products, include_gross=False, include_value=True)


def build_ltl_tender_email_from_tender(
    tender: dict[str, Any],
    template: str,
) -> dict[str, str]:
    """Fill LTL template from ``state.data['tender']``."""
    ctx = build_tender_email_input_from_tender(tender)
    products_block = _ltl_products_block(ctx.products)

    body_html = template.format(
        order_number=ctx.order_number,
        customer_po=ctx.customer_po,
        ship_date=ctx.ship_date,
        pickup_address=ctx.pickup_address,
        delivery_address=ctx.delivery_address,
        products_block=products_block,
    )

    subject = (
        f"(LTL) Load tender — Order {ctx.order_number}"
        if ctx.order_number
        else "(LTL) Load tender request"
    )
    return {"subject": subject, "body_html": body_html}


def build_ftl_tender_email_from_tender(
    tender: dict[str, Any],
    template: str,
) -> dict[str, str]:
    """Fill FTL template from ``state.data['tender']``."""
    ctx = build_tender_email_input_from_tender(tender)
    products_block = _ftl_products_block(ctx.products)

    body_html = template.format(
        order_number=ctx.order_number,
        customer_po=ctx.customer_po,
        ship_date=ctx.ship_date,
        delivery_date=ctx.delivery_date,
        delivery_address=ctx.delivery_address,
        products_block=products_block,
    )

    subject = (
        f"(FTL) Load tender — Order {ctx.order_number}"
        if ctx.order_number
        else "(FTL) Load tender request"
    )
    return {"subject": subject, "body_html": body_html}
