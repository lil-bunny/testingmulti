"""Appointment scheduling draft-ready Teams notification (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


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
        str(draft.get("to") or "").strip()
        and str(draft.get("subject") or "").strip()
        and str(draft.get("full_html") or "").strip()
    )


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

    return AppointmentSchedulingDraftDisplayFields(
        load_id=load_id,
        reference_number=str(data.get("reference_number") or "").strip(),
        customer_name=str(data.get("customer_name") or "").strip(),
        pickup_date=str(decision.get("selected_pickup_date") or "").strip(),
        delivery_date=str(decision.get("calculated_delivery_date") or "").strip(),
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
    delivery = fields.delivery_date or "unknown"
    return (
        f"Appointment draft for load {fields.load_id} is ready for portal review. "
        f"Proposed delivery: {delivery}."
    )


def draft_ready_facts(
    fields: AppointmentSchedulingDraftDisplayFields,
) -> list[tuple[str, str]]:
    return [
        ("Load ID", fields.load_id or "—"),
        ("Reference", fields.reference_number or "—"),
        ("Customer", fields.customer_name or "—"),
        ("Proposed pickup", fields.pickup_date or "—"),
        ("Proposed delivery", fields.delivery_date or "—"),
    ]


def _template_context(fields: AppointmentSchedulingDraftDisplayFields) -> dict[str, str]:
    return {
        "load_id": fields.load_id,
        "reference_number": fields.reference_number,
        "customer_name": fields.customer_name,
        "pickup_date": fields.pickup_date,
        "delivery_date": fields.delivery_date,
        "draft_subject": fields.draft_subject,
        "workflow_lifecycle_id": fields.workflow_lifecycle_id,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""
