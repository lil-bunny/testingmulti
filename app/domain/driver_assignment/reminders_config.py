"""``tenant_settings.driver_assignment.reminders`` — steps + email copy only."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator


if TYPE_CHECKING:
    from app.domain.reminder_schedule import ReminderStepSpec


class DriverAssignmentRemindersConfig(BaseModel):
    """
    Driver assignment reminder ladder.

    ``delay_hours`` on each step is always hours **before** pickup appointment.
    Catch-up and Celery expiry are code constants (see ``reminder_scheduling``).
    """

    model_config = ConfigDict(extra="ignore")

    steps: list[ReminderStepSpec] = Field(min_length=1)
    min_gap_hours: float = Field(default=3.0, ge=0)
    email_template_html: str | None = None
    default_body: str | None = None
    subject_templates: dict[str, str] | None = None
    payload_keys: list[str] | None = None

    def resolve_email_body(self) -> str | None:
        for raw in (self.email_template_html, self.default_body):
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if not out.get("steps") and out.get("offsets_before_pickup_hours"):
            offsets = out["offsets_before_pickup_hours"]
            out["steps"] = [
                {"step": i, "event_type": "reminder_due", "delay_hours": h}
                for i, h in enumerate(offsets, start=1)
            ]
        return out

    def resolve_steps(self) -> list[ReminderStepSpec]:
        return list(self.steps)


def parse_driver_assignment_reminders(
    tenant_settings: dict[str, Any] | None,
) -> DriverAssignmentRemindersConfig | None:
    """Validate ``tenant_settings.driver_assignment.reminders``."""
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("driver_assignment")
    if not isinstance(block, dict):
        return None
    raw = block.get("reminders")
    if not isinstance(raw, dict):
        return None
    try:
        return DriverAssignmentRemindersConfig.model_validate(raw)
    except Exception:
        return None
