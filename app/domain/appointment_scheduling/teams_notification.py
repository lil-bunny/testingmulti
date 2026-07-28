"""Appointment scheduling draft-ready Teams notification (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.appointment_scheduling.constants import COSTCO_PROPOSED_DELIVERY_WALL_TIME
from app.domain.appointment_scheduling.utils import is_costco_customer
from app.domain.tenant_settings.email_recipients import coerce_email_list


class AppointmentSchedulingTeamsNotificationSettings(BaseModel):
    """``tenant_settings.appointment_scheduling.teams_notification``."""

    model_config = ConfigDict(extra="ignore")

    teams_webhook_url: str = Field(min_length=1)
    message_title: str = "Appointment draft ready — Load {load_id}"
    message_body: str | None = None


@dataclass(frozen=True)
class AppointmentSchedulingDraftDisplayFields:
    load_id: str
    reference_number: str
    customer_name: str
    pickup_date: str
    delivery_date: str
    draft_subject: str
    workflow_lifecycle_id: str
    pickup_time: str = ""
    delivery_time: str = ""
    delivery_weekday: str = ""


def parse_appointment_scheduling_teams_notification_settings(
    tenant_settings: dict[str, Any] | None,
) -> AppointmentSchedulingTeamsNotificationSettings | None:
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("appointment_scheduling")
    if not isinstance(block, dict):
        return None
    raw = block.get("teams_notification")
    if not isinstance(raw, dict):
        return None
    try:
        return AppointmentSchedulingTeamsNotificationSettings.model_validate(raw)
    except Exception:
        return None


def _draft_ready(data: dict[str, Any]) -> bool:
    draft = data.get("email_draft")
    if not isinstance(draft, dict):
        return False
    return bool(
        coerce_email_list(draft.get("to"), required=False)
        and str(draft.get("subject") or "").strip()
        and str(draft.get("full_html") or "").strip()
    )


def _normalize_display_date(value: str) -> str:
    raw = (value or "").strip()
    if len(raw) == 10 and raw[4] == "-" and raw[7] == "-":
        year, month, day = raw.split("-")
        return f"{month}/{day}/{year}"
    return raw


def _appt_display(date: str, time: str = "", weekday: str = "") -> str:
    date = (date or "").strip()
    if not date:
        return "—"
    text = date
    time = (time or "").strip()
    weekday = (weekday or "").strip()
    if time:
        text = f"{text} · {time}"
    if weekday:
        text = f"{text} ({weekday})"
    return text


def display_fields_from_data(data: dict[str, Any]) -> AppointmentSchedulingDraftDisplayFields | None:
    if not _draft_ready(data):
        return None

    load_id = str(data.get("load_id") or "").strip()
    if not load_id:
        return None

    decision = data.get("llm_appointment_decision")
    if not isinstance(decision, dict):
        decision = {}

    draft = data.get("email_draft")
    draft_subject = str(draft.get("subject") or "").strip() if isinstance(draft, dict) else ""
    customer_name = str(data.get("customer_name") or "").strip()
    delivery_time = (
        COSTCO_PROPOSED_DELIVERY_WALL_TIME if is_costco_customer(customer_name) else ""
    )

    return AppointmentSchedulingDraftDisplayFields(
        load_id=load_id,
        reference_number=str(data.get("reference_number") or "").strip(),
        customer_name=customer_name,
        pickup_date=_normalize_display_date(str(decision.get("selected_pickup_date") or "")),
        delivery_date=_normalize_display_date(str(decision.get("calculated_delivery_date") or "")),
        pickup_time=str(decision.get("selected_pickup_time") or "").strip(),
        delivery_time=delivery_time,
        delivery_weekday=str(decision.get("calculated_delivery_weekday") or "").strip(),
        draft_subject=draft_subject,
        workflow_lifecycle_id=str(data.get("workflow_lifecycle_id") or "").strip(),
    )


def format_draft_ready_title(
    template: str,
    *,
    fields: AppointmentSchedulingDraftDisplayFields,
) -> str:
    ctx = _template_context(fields)
    try:
        return template.format(**ctx)
    except KeyError:
        return template.format_map(_SafeFormatMap(ctx))


def format_draft_ready_body(
    template: str | None,
    *,
    fields: AppointmentSchedulingDraftDisplayFields,
) -> str:
    if template and str(template).strip():
        ctx = _template_context(fields)
        try:
            return str(template).strip().format(**ctx)
        except KeyError:
            return str(template).strip().format_map(_SafeFormatMap(ctx))
    delivery = _appt_display(fields.delivery_date, fields.delivery_time, fields.delivery_weekday)
    if delivery == "—":
        delivery = "unknown"
    return (
        f"Appointment draft for load {fields.load_id} is ready for portal review. "
        f"Proposed delivery: {delivery}."
    )


def draft_ready_facts(
    fields: AppointmentSchedulingDraftDisplayFields,
) -> list[tuple[str, str]]:
    return [
        ("Reference", fields.reference_number or "—"),
        ("Customer", fields.customer_name or "—"),
        ("Proposed pickup", _appt_display(fields.pickup_date, fields.pickup_time)),
        (
            "Proposed delivery",
            _appt_display(fields.delivery_date, fields.delivery_time, fields.delivery_weekday),
        ),
    ]


def _template_context(fields: AppointmentSchedulingDraftDisplayFields) -> dict[str, str]:
    pickup_display = _appt_display(fields.pickup_date, fields.pickup_time)
    delivery_display = _appt_display(
        fields.delivery_date,
        fields.delivery_time,
        fields.delivery_weekday,
    )
    return {
        "load_id": fields.load_id,
        "reference_number": fields.reference_number,
        "customer_name": fields.customer_name,
        "pickup_date": fields.pickup_date,
        "delivery_date": fields.delivery_date,
        "pickup_time": fields.pickup_time,
        "delivery_time": fields.delivery_time,
        "delivery_weekday": fields.delivery_weekday,
        "pickup_display": pickup_display,
        "delivery_display": delivery_display,
        "draft_subject": fields.draft_subject,
        "workflow_lifecycle_id": fields.workflow_lifecycle_id,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""
