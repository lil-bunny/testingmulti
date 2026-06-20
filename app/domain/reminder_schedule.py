"""Shared reminder schedule contract for ``tenants.settings`` workflow blocks."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReminderStepSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delay_hours: float = Field(gt=0)
    event_type: str = "reminder_due"
    step: int | None = None


class ReminderVariantSteps(BaseModel):
    """Optional wrapper when JSON uses ``{ \"steps\": [...] }`` per variant key."""

    model_config = ConfigDict(extra="ignore")

    steps: list[ReminderStepSpec] = Field(min_length=1)


class WorkflowRemindersConfig(BaseModel):
    """
    ``tenant_settings.<workflow_subkey>.reminders`` — schedule + optional email copy.

    Use flat ``steps`` or ``variants`` + ``variant_selector`` (e.g. load_type → ltl/ftl).
    ``delay_hours`` means hours after schedule when ``schedule_mode=delay_from_start`` (POD),
    or hours before pickup when ``schedule_mode=before_pickup`` (driver assignment).
    Email HTML: prefer ``email_template_html``; ``default_body`` is legacy fallback.
    """

    model_config = ConfigDict(extra="ignore")

    expire_grace_hours: float = Field(default=2.0, gt=0)
    schedule_mode: Literal["delay_from_start", "before_pickup"] = "delay_from_start"
    offsets_before_pickup_hours: list[float] | None = None
    steps: list[ReminderStepSpec] | None = None
    variants: dict[str, list[ReminderStepSpec]] | None = None
    variant_selector: Literal["load_type"] | None = None
    schedule_on_event_type: str | None = None
    skip_sub_statuses: list[str] = Field(default_factory=list)
    email_template_html: str | None = None
    default_body: str | None = None
    subject_templates: dict[str, str] | None = None
    payload_keys: list[str] | None = None

    def resolve_email_body(self) -> str | None:
        """HTML/plain body for reminder emails; ``email_template_html`` wins over ``default_body``."""
        for raw in (self.email_template_html, self.default_body):
            if raw is not None and str(raw).strip():
                return str(raw).strip()
        return None

    @model_validator(mode="before")
    @classmethod
    def _normalize_variants(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        out = dict(data)
        if (
            out.get("schedule_mode") == "before_pickup"
            and not out.get("steps")
            and out.get("offsets_before_pickup_hours")
        ):
            offsets = out["offsets_before_pickup_hours"]
            out["steps"] = [
                {"step": i, "event_type": "reminder_due", "delay_hours": h}
                for i, h in enumerate(offsets, start=1)
            ]
        raw_variants = out.get("variants")
        if not isinstance(raw_variants, dict):
            return out
        normalized: dict[str, list] = {}
        for key, value in raw_variants.items():
            if isinstance(value, dict) and "steps" in value:
                normalized[str(key)] = value["steps"]
            else:
                normalized[str(key)] = value
        out["variants"] = normalized
        return out

    @model_validator(mode="after")
    def _steps_or_variants(self) -> WorkflowRemindersConfig:
        if self.schedule_mode == "before_pickup":
            if self.variants:
                raise ValueError("variants is not supported when schedule_mode is before_pickup")
            if not self.steps:
                raise ValueError("steps is required when schedule_mode is before_pickup")
            return self
        has_steps = bool(self.steps)
        has_variants = bool(self.variants)
        if has_steps == has_variants:
            raise ValueError("WorkflowRemindersConfig requires exactly one of steps or variants")
        if has_variants and not self.variant_selector:
            raise ValueError("variant_selector is required when variants is set")
        return self

    def resolve_steps(self, *, variant_key: str | None = None) -> list[ReminderStepSpec]:
        if self.steps:
            return list(self.steps)
        if not self.variants:
            return []
        key = (variant_key or "").strip().lower()
        if key not in self.variants:
            raise KeyError(f"reminder variant {key!r} not in variants")
        return list(self.variants[key])
