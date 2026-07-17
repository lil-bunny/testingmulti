"""Typed ``tenants.settings`` contract for the t3ra tenant (slug ``t3ra``)."""

from __future__ import annotations

from typing import Annotated, Any, TYPE_CHECKING

from pydantic import AliasChoices, BaseModel, BeforeValidator, ConfigDict, Field

if TYPE_CHECKING:
    from app.domain.driver_assignment.partial_follow_up_email import (
        DriverAssignmentPartialFollowUpEmailConfig,
    )
    from app.domain.driver_assignment.confirmation_email import (
        DriverAssignmentConfirmationEmailConfig,
    )
    from app.domain.tenant_settings.tms import TmsSettings
    from app.domain.tenant_settings.email_recipients import EmailRecipients, InboundRoutingEmails
    from app.domain.reminder_schedule import WorkflowRemindersConfig
    from app.domain.driver_assignment.reminders_config import DriverAssignmentRemindersConfig
    from app.domain.driver_assignment.escalation import DriverAssignmentEscalateSettings
    from app.domain.pod_lifecycle.teams_notification import PodLifecycleTeamsNotificationSettings


class ShadowBypassLoadEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    load_id: str | None = None
    shipment_id: str | None = None


class T3raPodLifecycleSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shadow_mode: bool = False
    shadow_emails: EmailRecipients | None = None
    shadow_bypass_loads: list[ShadowBypassLoadEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("shadow_bypass_loads", "shadow_live_loads"),
    )
    reminders: WorkflowRemindersConfig
    teams_notification: PodLifecycleTeamsNotificationSettings | None = None


class T3raDriverAssignmentSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    shadow_mode: bool = False
    shadow_emails: EmailRecipients | None = None
    shadow_bypass_loads: list[ShadowBypassLoadEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("shadow_bypass_loads", "shadow_live_loads"),
    )
    reminders: DriverAssignmentRemindersConfig
    confirmation_email: DriverAssignmentConfirmationEmailConfig | None = None
    partial_follow_up_email: DriverAssignmentPartialFollowUpEmailConfig | None = None
    escalate_driver: DriverAssignmentEscalateSettings | None = None


class T3raPodLifecyclePrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page_extraction: str
    vs_ratecon_summary: str
    vs_ratecon_semantic_match: str
    attachment_classifier: str


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


class MikeyAccountSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    account_id: str
    email_alias: str | None = None


def _coerce_mikey_account_id(value: Any) -> MikeyAccountSettings:
    if isinstance(value, str):
        return MikeyAccountSettings(account_id=value.strip())
    if isinstance(value, MikeyAccountSettings):
        return value
    if isinstance(value, dict):
        return MikeyAccountSettings.model_validate(value)
    raise ValueError("mikey_account_id must be a string or {account_id, email_alias?} object")


MikeyAccountId = Annotated[MikeyAccountSettings, BeforeValidator(_coerce_mikey_account_id)]


class T3raTenantSettings(BaseModel):
    """
    Root ``tenants.settings`` JSON for t3ra.

    TMS partner + user auth live under ``tms``; workflow config at root.
    """

    model_config = ConfigDict(extra="ignore")

    enabledProcesses: list[str] = Field(default_factory=list)
    inbound_routing_emails: InboundRoutingEmails
    mikey_account_id: MikeyAccountId
    tms: TmsSettings
    prompts: T3raPrompts
    pod_lifecycle: T3raPodLifecycleSettings
    driver_assignment: T3raDriverAssignmentSettings | None = None
