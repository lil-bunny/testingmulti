"""Typed ``tenants.settings`` contract for the Gelita tenant (slug ``gelita``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.prompt_step_keys import LOAD_TENDERING_CARRIER_ACK
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.domain.tenant_settings.email_recipients import (
    EmailRecipients,
    InboundRoutingEmails,
    coerce_email_list,
)
from app.domain.tenant_settings.workflow_error_alerts import WorkflowErrorAlertSettings

# Reusable list fields: required TO accepts str | list; optional CC/BCC default empty.
RequiredEmailList = list[str]
OptionalEmailList = list[str]


class GelitaPickupAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city: str
    name: str
    state: str
    country: str
    address1: str
    postal_code: str


class GelitaSendTenderEmailSettings(BaseModel):
    """``load_tendering.{ltl|ftl}.send_tender_email``."""

    model_config = ConfigDict(extra="ignore")

    vendor_email: RequiredEmailList = Field(min_length=1)
    vendor_cc: OptionalEmailList = Field(default_factory=list)
    vendor_bcc: OptionalEmailList = Field(default_factory=list)
    email_subject: str
    email_template_html: str

    @field_validator("vendor_email", mode="before")
    @classmethod
    def _vendor_email(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=True)

    @field_validator("vendor_cc", "vendor_bcc", mode="before")
    @classmethod
    def _vendor_cc_bcc(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=False)

    def recipients(self) -> EmailRecipients:
        return EmailRecipients(
            to=self.vendor_email,
            cc=self.vendor_cc,
            bcc=self.vendor_bcc,
        )


class GelitaSendTenderReminderSettings(BaseModel):
    """In-thread reminder email copy (timing lives under ``load_tendering.reminders``)."""

    model_config = ConfigDict(extra="ignore")

    reminder_body: str


class GelitaEscalateTenderSettings(BaseModel):
    """``load_tendering.{ltl|ftl}.escalate_tender``."""

    model_config = ConfigDict(extra="ignore")

    escalation_email_body: str
    escalation_notify_email: RequiredEmailList = Field(min_length=1)
    escalation_cc: OptionalEmailList = Field(default_factory=list)
    escalation_bcc: OptionalEmailList = Field(default_factory=list)
    escalation_email_subject: str

    @field_validator("escalation_notify_email", mode="before")
    @classmethod
    def _escalation_to(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=True)

    @field_validator("escalation_cc", "escalation_bcc", mode="before")
    @classmethod
    def _escalation_cc_bcc(cls, value: Any) -> list[str]:
        return coerce_email_list(value, required=False)

    def recipients(self) -> EmailRecipients:
        return EmailRecipients(
            to=self.escalation_notify_email,
            cc=self.escalation_cc,
            bcc=self.escalation_bcc,
        )


class GelitaLoadTypeBranch(BaseModel):
    """``load_tendering.ltl`` or ``load_tendering.ftl``."""

    model_config = ConfigDict(extra="ignore")

    send_tender_email: GelitaSendTenderEmailSettings
    send_tender_reminder: GelitaSendTenderReminderSettings
    escalate_tender: GelitaEscalateTenderSettings


def normalize_pallet_type_label(value: str | None) -> str:
    """Case/whitespace/hyphen insensitive label for ``pack_codes.pallet_type`` lookup."""
    collapsed = " ".join(str(value or "").strip().lower().split())
    return collapsed.replace("-", " ")


class GelitaPalletProfile(BaseModel):
    """One Gelita pallet family: gross-weight tare and FTL/LTL pallet-count threshold."""

    model_config = ConfigDict(extra="ignore")

    weight_lbs: float
    threshold: int
    match: list[str] = Field(min_length=1)


class GelitaTenderCalculateSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallet_profiles: dict[str, GelitaPalletProfile]
    gelita_pickup_address: GelitaPickupAddress

    def resolve_pallet_type(self, pallet_type: str | None) -> tuple[str, GelitaPalletProfile]:
        """Map ``pack_codes.pallet_type`` to a configured profile key."""
        norm = normalize_pallet_type_label(pallet_type)
        if not norm:
            raise ValueError("pack_codes.pallet_type is empty")
        for key, profile in self.pallet_profiles.items():
            for label in profile.match:
                if normalize_pallet_type_label(label) == norm:
                    return key, profile
        raise ValueError(f"unknown pack_codes.pallet_type: {pallet_type!r}")


class GelitaLoadTenderingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig
    ltl: GelitaLoadTypeBranch
    ftl: GelitaLoadTypeBranch
    tender_calculate: GelitaTenderCalculateSettings
    workflow_error_alerts: WorkflowErrorAlertSettings | None = None


class GelitaTenantSettings(BaseModel):
    """
    Root ``tenants.settings`` JSON for Gelita.

    Other tenants should define their own model under ``app/domain/tenant_settings/``.
    """

    model_config = ConfigDict(extra="ignore")

    enabledProcesses: list[str] = Field(default_factory=list)
    inbound_routing_emails: InboundRoutingEmails
    ana_at_gelita_account_id: str
    ana_gelita_at_freightx_ai_account_id: str
    prompts: dict[str, str]
    load_tendering: GelitaLoadTenderingSettings
    workflow_error_alerts: WorkflowErrorAlertSettings | None = None

    @model_validator(mode="after")
    def _require_carrier_ack_prompt(self) -> GelitaTenantSettings:
        ref = (self.prompts.get(LOAD_TENDERING_CARRIER_ACK) or "").strip()
        if not ref:
            raise ValueError(
                f"prompts must include non-empty {LOAD_TENDERING_CARRIER_ACK!r}"
            )
        return self

    def branch_for_load_type(self, load_type: str | None) -> GelitaLoadTypeBranch:
        bucket: Literal["ltl", "ftl"] = (
            "ftl" if str(load_type or "").strip().upper() == "FTL" else "ltl"
        )
        return getattr(self.load_tendering, bucket)
