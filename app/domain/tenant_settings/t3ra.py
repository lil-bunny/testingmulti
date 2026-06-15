"""Typed ``tenants.settings`` contract for the t3ra tenant (slug ``t3ra``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.domain.tenant_settings.email_recipients import InboundRoutingEmails
from app.domain.tenant_settings.tms import TmsSettings


class T3raPodLifecycleSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig


class T3raTenantSettings(BaseModel):
    """
    Root ``tenants.settings`` JSON for t3ra.

    TMS partner + user auth live under ``tms``; workflow config at root.
    """

    model_config = ConfigDict(extra="ignore")

    inbound_routing_emails: InboundRoutingEmails
    mikey_account_id: str
    tms: TmsSettings
    prompts: dict[str, str] = Field(default_factory=dict)
    pod_lifecycle: T3raPodLifecycleSettings
