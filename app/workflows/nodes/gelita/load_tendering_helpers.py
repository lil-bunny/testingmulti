"""Shared helpers for Gelita ``load_tendering`` node modules."""

from __future__ import annotations

from html import escape
from typing import Any

from app.domain.lifecycle_transition import LifecycleTransitionCommand
# from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db

__all__ = [
    "build_gelita_tender_email",
    "build_gelita_ftl_tender_email",
    "record_tender_calc_failure",
    # "status_type_from_db",
    # "sub_status_type_from_db",
]
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService


def _html_address_block(text: str) -> str:
    """Turn a multi-line USPS block into HTML lines separated by ``<br />``."""
    if not text:
        return ""
    return "<br />".join(
        escape(line.strip()) for line in str(text).splitlines() if line.strip()
    )


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

    subject = f"Load tender — Order {order_number}" if order_number else "Load tender request"
    return {"subject": subject, "body_html": body_html}


def build_gelita_ftl_tender_email(
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

    subject = f"Load tender — Order {order_number}" if order_number else "Load tender request"
    return {"subject": subject, "body_html": body_html}


_CALC_FAILURE_DESCRIPTIONS: dict[str, str] = {
    "missing_pack_code": "Pack code missing or inactive",
    "missing_qty_per_unit": "Pack code qty_per_unit missing",
    "missing_total_qty": "Pack code total_qty missing",
    "missing_tenant_id": "Missing tenant_id",
    "missing_tender_id": "Missing tender_id",
    "tender_not_found": "Tender not found",
}


def record_tender_calc_failure(state: Any, *, error_code: str) -> None:
    """
    Mark lifecycle ``failed`` and append a status_change activity log (status only).

    Call from ``calculate_tender_params`` when the run cannot continue.
    """
    wl_id = str(getattr(state, "data", {}).get("workflow_lifecycle_id") or "").strip()
    tenant_id = (getattr(state, "tenant_id", None) or "").strip()
    run_id = str(getattr(state, "execution_id", None) or "").strip()
    tender_id = str(getattr(state, "data", {}).get("tender_id") or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return

    description = _CALC_FAILURE_DESCRIPTIONS.get(error_code, error_code)
    pack_code = str(getattr(state, "data", {}).get("pack_code") or "").strip()
    metadata: dict[str, Any] = {"error": error_code, "tender_id": tender_id}
    if pack_code:
        metadata["pack_code"] = pack_code

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply(
        LifecycleTransitionCommand(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=StatusType.FAILED,
            description=description,
            actor_type=ActorType.SYSTEM,
            metadata=metadata,
        )
    )
