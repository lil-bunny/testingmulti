"""Typed ``tenants.settings`` contract for the Gelita tenant (slug ``gelita``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.tenant_settings.email_recipients import EmailRecipients, coerce_email_list

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
    model_config = ConfigDict(extra="ignore")

    reminder_body: str
    reminder_1_hours: float
    reminder_2_hours: float | None = None


class GelitaEscalateTenderSettings(BaseModel):
    """``load_tendering.{ltl|ftl}.escalate_tender``."""

    model_config = ConfigDict(extra="ignore")

    escalation_hours: float
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


class GelitaTenderCalculateSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallet_threshold: int
    pallet_weight_lbs: float
    gelita_pickup_address: GelitaPickupAddress


class GelitaDeliveryLocationsExcelSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delivery_locations_max_rows: int
    delivery_locations_tab_name: str
    delivery_locations_share_url: str


class GelitaLoadTenderingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ltl: GelitaLoadTypeBranch
    ftl: GelitaLoadTypeBranch
    tender_calculate: GelitaTenderCalculateSettings
    delivery_locations_excel: GelitaDeliveryLocationsExcelSettings


class GelitaTenantSettings(BaseModel):
    """
    Root ``tenants.settings`` JSON for Gelita.

    Other tenants should define their own model under ``app/domain/tenant_settings/``.
    """

    model_config = ConfigDict(extra="ignore")

    enabledProcesses: list[str] = Field(default_factory=list)
    email_webhook_name: str
    ana_at_gelita_account_id: str
    ana_gelita_at_freightx_ai_account_id: str
    load_tendering: GelitaLoadTenderingSettings

    def branch_for_load_type(self, load_type: str | None) -> GelitaLoadTypeBranch:
        bucket: Literal["ltl", "ftl"] = (
            "ftl" if str(load_type or "").strip().upper() == "FTL" else "ltl"
        )
        return getattr(self.load_tendering, bucket)
