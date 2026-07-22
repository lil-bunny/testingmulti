"""Tenant ``appointment_scheduling.confirmation_reply`` config (pure, no I/O).

Placeholders for ``template_html`` / ``body_text``:
  {load_id}, {reference_number}, {customer_name}, {confirmed_delivery_at},
  {shipment_id}, {workflow_lifecycle_id}, {pickup_date}, {delivery_date}

Literal braces in HTML/CSS must be escaped as ``{{`` / ``}}``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

DEFAULT_CONFIRMATION_REPLY_BODY = "Confirmed, Thank You"


class AppointmentSchedulingConfirmationReplySettings(BaseModel):
    """Optional HTML/plain reply after customer confirms delivery appointment."""

    model_config = ConfigDict(extra="ignore")

    template_html: str | None = None
    body_text: str | None = None


@dataclass(frozen=True)
class ConfirmationReplyDisplayFields:
    load_id: str
    reference_number: str
    customer_name: str
    confirmed_delivery_at: str
    shipment_id: str
    workflow_lifecycle_id: str
    pickup_date: str
    delivery_date: str


def parse_appointment_scheduling_confirmation_reply_settings(
    tenant_settings: dict[str, Any] | None,
) -> AppointmentSchedulingConfirmationReplySettings | None:
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("appointment_scheduling")
    if not isinstance(block, dict):
        return None
    raw = block.get("confirmation_reply")
    if not isinstance(raw, dict):
        return None
    try:
        return AppointmentSchedulingConfirmationReplySettings.model_validate(raw)
    except Exception:
        return None


def display_fields_from_data(data: dict[str, Any]) -> ConfirmationReplyDisplayFields:
    decision = data.get("llm_scheduling_decision")
    if not isinstance(decision, dict):
        decision = {}

    pickup_date = str(
        data.get("pickup_date") or decision.get("selected_pickup_date") or ""
    ).strip()
    delivery_date = str(
        data.get("delivery_date")
        or data.get("confirmed_delivery_at")
        or decision.get("calculated_delivery_date")
        or ""
    ).strip()

    return ConfirmationReplyDisplayFields(
        load_id=str(data.get("load_id") or "").strip(),
        reference_number=str(data.get("reference_number") or "").strip(),
        customer_name=str(data.get("customer_name") or "").strip(),
        confirmed_delivery_at=str(data.get("confirmed_delivery_at") or "").strip(),
        shipment_id=str(data.get("shipment_id") or "").strip(),
        workflow_lifecycle_id=str(data.get("workflow_lifecycle_id") or "").strip(),
        pickup_date=pickup_date,
        delivery_date=delivery_date,
    )


def render_confirmation_reply(
    template: str,
    *,
    fields: ConfirmationReplyDisplayFields,
) -> str:
    ctx = _template_context(fields)
    try:
        return str(template).strip().format(**ctx)
    except KeyError:
        return str(template).strip().format_map(_SafeFormatMap(ctx))


def resolve_confirmation_reply_body(
    tenant_settings: dict[str, Any] | None,
    data: dict[str, Any],
) -> str:
    """Return thread-reply body: template_html > body_text > code default."""
    fields = display_fields_from_data(data)
    cfg = parse_appointment_scheduling_confirmation_reply_settings(tenant_settings)
    if cfg is not None:
        html = str(cfg.template_html or "").strip()
        if html:
            return render_confirmation_reply(html, fields=fields)
        text = str(cfg.body_text or "").strip()
        if text:
            return render_confirmation_reply(text, fields=fields)
    return DEFAULT_CONFIRMATION_REPLY_BODY


def _template_context(fields: ConfirmationReplyDisplayFields) -> dict[str, str]:
    return {
        "load_id": fields.load_id,
        "reference_number": fields.reference_number,
        "customer_name": fields.customer_name,
        "confirmed_delivery_at": fields.confirmed_delivery_at,
        "shipment_id": fields.shipment_id,
        "workflow_lifecycle_id": fields.workflow_lifecycle_id,
        "pickup_date": fields.pickup_date,
        "delivery_date": fields.delivery_date,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


__all__ = (
    "DEFAULT_CONFIRMATION_REPLY_BODY",
    "AppointmentSchedulingConfirmationReplySettings",
    "ConfirmationReplyDisplayFields",
    "display_fields_from_data",
    "parse_appointment_scheduling_confirmation_reply_settings",
    "render_confirmation_reply",
    "resolve_confirmation_reply_body",
)
