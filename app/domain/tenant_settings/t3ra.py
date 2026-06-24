"""Typed ``tenants.settings`` contract for the t3ra tenant (slug ``t3ra``)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.domain.driver_assignment.confirmation_email import (
    DriverAssignmentConfirmationEmailConfig,
)
from app.domain.driver_assignment.escalation import DriverAssignmentEscalateSettings
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.domain.tenant_settings.email_recipients import InboundRoutingEmails
from app.domain.tenant_settings.tms import TmsSettings


class T3raPodLifecyclePrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_extraction: str
    vs_ratecon_summary: str
    vs_ratecon_semantic_match: str


class T3raRateconPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_extraction: str


class T3raPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pod_lifecycle: T3raPodLifecyclePrompts
    ratecon: T3raRateconPrompts


class T3raPodLifecycleSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig


class T3raDriverAssignmentSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig
    confirmation_email: DriverAssignmentConfirmationEmailConfig | None = None
    escalate_driver: DriverAssignmentEscalateSettings | None = None


class T3raPodLifecyclePrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_extraction: str
    vs_ratecon_summary: str
    vs_ratecon_semantic_match: str


class T3raRateconPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_extraction: str


class T3raDriverAssignmentPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    driver_details: str


class T3raPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pod_lifecycle: T3raPodLifecyclePrompts
    ratecon: T3raRateconPrompts
    driver_assignment: T3raDriverAssignmentPrompts | None = None


class T3raTenantSettings(BaseModel):
    """
    Root ``tenants.settings`` JSON for t3ra.

    TMS partner + user auth live under ``tms``; workflow config at root.
    """

    model_config = ConfigDict(extra="ignore")

    enabledProcesses: list[str] = Field(default_factory=list)
    inbound_routing_emails: InboundRoutingEmails
    mikey_account_id: str
    tms: TmsSettings
    prompts: T3raPrompts
    pod_lifecycle: T3raPodLifecycleSettings
    driver_assignment: T3raDriverAssignmentSettings | None = None
