"""Driver assignment escalation settings and message context (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reminder_schedule import WorkflowRemindersConfig


class DriverAssignmentEscalateSettings(BaseModel):
    """``tenant_settings.driver_assignment.escalate_driver``."""

    model_config = ConfigDict(extra="ignore")

    teams_webhook_url: str = Field(min_length=1)
    message_title: str = "Driver details escalation — Load {load_id}"
    message_body: str | None = None


@dataclass(frozen=True)
class DriverEscalationDisplayFields:
    load_id: str
    shipment_id: str
    shipments_row_id: str
    workflow_lifecycle_id: str
    carrier_name: str
    customer_name: str
    delivery_date: str
    pickup_at: str
    pickup_timezone: str
    current_sub_status: str


def parse_driver_assignment_escalate_settings(
    tenant_settings: dict[str, Any] | None,
) -> DriverAssignmentEscalateSettings | None:
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("driver_assignment")
    if not isinstance(block, dict):
        return None
    raw = block.get("escalate_driver")
    if not isinstance(raw, dict):
        return None
    try:
        return DriverAssignmentEscalateSettings.model_validate(raw)
    except Exception:
        return None


def skip_sub_statuses_from_driver_assignment_settings(
    tenant_settings: dict[str, Any] | None,
) -> frozenset[str]:
    if not isinstance(tenant_settings, dict):
        return frozenset()
    block = tenant_settings.get("driver_assignment")
    if not isinstance(block, dict):
        return frozenset()
    raw = block.get("reminders")
    if not isinstance(raw, dict):
        return frozenset()
    try:
        cfg = WorkflowRemindersConfig.model_validate(raw)
    except Exception:
        return frozenset()
    return frozenset(s.strip() for s in cfg.skip_sub_statuses if str(s).strip())


def format_driver_escalation_title(
    template: str,
    *,
    fields: DriverEscalationDisplayFields,
) -> str:
    ctx = _template_context(fields)
    try:
        return template.format(**ctx)
    except KeyError:
        return template.format_map(_SafeFormatMap(ctx))


def format_driver_escalation_body(
    template: str | None,
    *,
    fields: DriverEscalationDisplayFields,
) -> str:
    if template and str(template).strip():
        ctx = _template_context(fields)
        try:
            return str(template).strip().format(**ctx)
        except KeyError:
            return str(template).strip().format_map(_SafeFormatMap(ctx))
    return (
        "Carrier has not provided driver details after all reminder emails. "
        "Please follow up manually."
    )


def driver_escalation_facts(
    fields: DriverEscalationDisplayFields,
) -> list[tuple[str, str]]:
    return [
        ("Load ID", fields.load_id or "—"),
        ("Turvo shipment ID", fields.shipment_id or "—"),
        ("Shipments row ID", fields.shipments_row_id or "—"),
        ("Lifecycle ID", fields.workflow_lifecycle_id or "—"),
        ("Carrier", fields.carrier_name or "—"),
        ("Customer", fields.customer_name or "—"),
        ("Pickup", fields.pickup_at or "—"),
        ("Pickup timezone", fields.pickup_timezone or "—"),
        ("Delivery date", fields.delivery_date or "—"),
        ("Current sub-status", fields.current_sub_status or "—"),
    ]


def _template_context(fields: DriverEscalationDisplayFields) -> dict[str, str]:
    return {
        "load_id": fields.load_id,
        "shipment_id": fields.shipment_id,
        "shipments_row_id": fields.shipments_row_id,
        "workflow_lifecycle_id": fields.workflow_lifecycle_id,
        "carrier_name": fields.carrier_name,
        "customer_name": fields.customer_name,
        "delivery_date": fields.delivery_date,
        "pickup_at": fields.pickup_at,
        "pickup_timezone": fields.pickup_timezone,
        "current_sub_status": fields.current_sub_status,
    }


class _SafeFormatMap(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""
