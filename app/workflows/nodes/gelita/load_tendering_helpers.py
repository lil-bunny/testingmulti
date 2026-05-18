"""Shared helpers for Gelita ``load_tendering`` node modules."""

from __future__ import annotations

from typing import Any

from app.models.status import StatusSubType, StatusType


def build_gelita_tender_email(
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
    pickup_address = tender_data.get("pickup_address") or ""
    delivery_address = tender_data.get("delivery_address") or ""

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

    subject = f"Load tender — Order {order_number}" if order_number else "Load tender request"
    return {"subject": subject, "body_html": body_html}


def status_type_from_db(raw: str | None) -> StatusType | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return StatusType(str(raw).strip())
    except ValueError:
        return None


def sub_status_type_from_db(raw: str | None) -> StatusSubType | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return StatusSubType(str(raw).strip())
    except ValueError:
        return None
