"""Build LTL/FTL load-tender email bodies from tenant HTML templates."""

from __future__ import annotations

from html import escape
from typing import Any

__all__ = [
    "build_ltl_tender_email",
    "build_ftl_tender_email",
]


def _html_address_block(text: str) -> str:
    """Turn a multi-line USPS block into HTML lines separated by ``<br />``."""
    if not text:
        return ""
    return "<br />".join(
        escape(line.strip()) for line in str(text).splitlines() if line.strip()
    )


def build_ltl_tender_email(
    tender_data: dict[str, Any],
    calculated_params: dict[str, Any],
    template: str,
) -> dict[str, str]:
    """
    Fill ``template`` with tender + calculation placeholders.

    Returns keys ``subject`` and ``body_html``.
    """
    order_number = tender_data.get("order_number") or ""
    customer_po = tender_data.get("customer_po") or ""
    ship_date = tender_data.get("ship_date") or ""
    product_name = tender_data.get("product_name") or ""
    pickup_address = _html_address_block(tender_data.get("pickup_address") or "")
    delivery_address = _html_address_block(tender_data.get("delivery_address") or "")

    pieces = calculated_params.get("pieces")
    if pieces is None:
        pieces = calculated_params.get("pieces_count")
    pallets = calculated_params.get("pallets")
    if pallets is None:
        pallets = calculated_params.get("pallets_count")
    gross_weight = calculated_params.get("gross_weight")

    body_html = template.format(
        order_number=order_number,
        customer_po=customer_po,
        ship_date=ship_date,
        product_name=product_name,
        pieces=pieces if pieces is not None else "",
        pallets=pallets if pallets is not None else "",
        gross_weight=gross_weight if gross_weight is not None else "",
        pickup_address=pickup_address,
        delivery_address=delivery_address,
    )

    subject = (
        f"(LTL) Load tender — Order {order_number}"
        if order_number
        else "(LTL) Load tender request"
    )
    return {"subject": subject, "body_html": body_html}


def build_ftl_tender_email(
    tender_data: dict[str, Any],
    calculated_params: dict[str, Any],
    template: str,
) -> dict[str, str]:
    """
    Fill FTL ``template`` with deliver-to, dates, value, and pallet placeholders.

    Returns keys ``subject`` and ``body_html``.
    """
    order_number = tender_data.get("order_number") or ""
    customer_po = tender_data.get("customer_po") or ""
    ship_date = tender_data.get("ship_date") or ""
    delivery_date = tender_data.get("delivery_date") or ""
    order_value = tender_data.get("order_value") or ""
    delivery_address = _html_address_block(tender_data.get("delivery_address") or "")

    pallets = calculated_params.get("pallets")
    if pallets is None:
        pallets = calculated_params.get("pallets_count")

    body_html = template.format(
        order_number=order_number,
        customer_po=customer_po,
        ship_date=ship_date,
        delivery_date=delivery_date,
        value=order_value,
        pallets_count=pallets if pallets is not None else "",
        delivery_address=delivery_address,
    )

    subject = (
        f"(FTL) Load tender — Order {order_number}"
        if order_number
        else "(FTL) Load tender request"
    )
    return {"subject": subject, "body_html": body_html}
