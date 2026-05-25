"""Typed ``tenants.settings`` contract for the t3ra tenant (slug ``t3ra``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.reminder_schedule import WorkflowRemindersConfig


class T3raPodLifecycleSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig


class T3raTenantSettings(BaseModel):
    """Root ``tenants.settings`` JSON for t3ra (POD and future workflows)."""

    model_config = ConfigDict(extra="ignore")

    pod_lifecycle: T3raPodLifecycleSettings
