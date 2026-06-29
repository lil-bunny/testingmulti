"""Typed ``tenants.settings`` contract for the Gelita tenant (slug ``gelita``)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.domain.tenant_settings.email_recipients import (
    EmailRecipients,
    InboundRoutingEmails,
)
from app.domain.tenant_settings.workflow_error_alerts import WorkflowErrorAlertSettings
from app.integrations.pgeocode.country_aliases import get_country_iso

class GelitaPickupAddress(BaseModel):
    model_config = ConfigDict(extra="ignore")

    city: str
    name: str
    state: str
    country: str
    address1: str
    postal_code: int

    @field_validator("postal_code", mode="before")
    @classmethod
    def _coerce_postal_code(cls, value: Any) -> int:
        if isinstance(value, bool):
            raise ValueError("postal_code must be an integer")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.isdigit():
                return int(stripped)
        raise ValueError("postal_code must be an integer")


class GelitaSendTenderEmailSettings(BaseModel):
    """``load_tendering.{ltl|ftl}.send_tender_email``."""

    model_config = ConfigDict(extra="ignore")

    emails: EmailRecipients
    email_subject: str
    email_template_html: str

    def recipients(self) -> EmailRecipients:
        return self.emails


class GelitaSendTenderReminderSettings(BaseModel):
    """In-thread reminder email copy (timing lives under ``load_tendering.reminders``)."""

    model_config = ConfigDict(extra="ignore")

    reminder_body: str


class GelitaEscalateTenderSettings(BaseModel):
    """``load_tendering.{ltl|ftl}.escalate_tender``."""

    model_config = ConfigDict(extra="ignore")

    emails: EmailRecipients
    escalation_email_body: str
    escalation_email_subject: str

    def recipients(self) -> EmailRecipients:
        return self.emails


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
    default: bool = False


class GelitaTenderCalculateSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    pallet_profiles: dict[str, GelitaPalletProfile]
    gelita_pickup_address: GelitaPickupAddress

    def _default_pallet_profile(self) -> tuple[str, GelitaPalletProfile]:
        """Return the single profile marked ``default: true`` in tenant settings."""
        matches = [
            (key, profile)
            for key, profile in self.pallet_profiles.items()
            if profile.default
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError("multiple default pallet profiles in tenant settings")
        raise ValueError("no default pallet profile in tenant settings")

    def resolve_pallet_type(self, pallet_type: str | None) -> tuple[str, GelitaPalletProfile]:
        """Map ``pack_codes.pallet_type`` to a configured profile key.

        Empty or unmatched labels fall back to the profile with ``default: true``.
        """
        norm = normalize_pallet_type_label(pallet_type)
        if norm:
            for key, profile in self.pallet_profiles.items():
                for label in profile.match:
                    if normalize_pallet_type_label(label) == norm:
                        return key, profile
        return self._default_pallet_profile()


class GelitaDomesticDeliverySettings(BaseModel):
    """``load_tendering.domestic_delivery`` — ISO2 codes treated as domestic for routing."""

    model_config = ConfigDict(extra="ignore")

    country_iso_codes: list[str] = Field(min_length=1)

    @field_validator("country_iso_codes", mode="before")
    @classmethod
    def _normalize_iso_codes(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("country_iso_codes must be a list")
        codes = [str(item).strip().upper() for item in value if str(item).strip()]
        if not codes:
            raise ValueError("country_iso_codes must not be empty")
        return codes

    def is_domestic_delivery_country(self, country: str | None) -> bool:
        iso = get_country_iso(country)
        if iso is None:
            return True
        return iso in frozenset(self.country_iso_codes)

    def is_international_delivery_country(self, country: str | None) -> bool:
        iso = get_country_iso(country)
        if iso is None:
            return False
        return iso not in frozenset(self.country_iso_codes)


class GelitaSkippedPackCodesSettings(BaseModel):
    """``load_tendering.skipped_pack_codes`` — pack codes that skip domestic processing."""

    model_config = ConfigDict(extra="ignore")

    pack_codes: list[str] = Field(default_factory=list)

    @field_validator("pack_codes", mode="before")
    @classmethod
    def _normalize_pack_codes(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if not isinstance(value, list):
            raise ValueError("pack_codes must be a list")
        return [str(item).strip() for item in value if str(item).strip()]


class GelitaLoadTenderingPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    carrier_ack: str


class GelitaPrompts(BaseModel):
    model_config = ConfigDict(extra="ignore")

    load_tendering: GelitaLoadTenderingPrompts


class GelitaLoadTenderingSettings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reminders: WorkflowRemindersConfig
    ltl: GelitaLoadTypeBranch
    ftl: GelitaLoadTypeBranch
    tender_calculate: GelitaTenderCalculateSettings
    domestic_delivery: GelitaDomesticDeliverySettings
    skipped_pack_codes: GelitaSkippedPackCodesSettings = Field(
        default_factory=GelitaSkippedPackCodesSettings
    )
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
    prompts: GelitaPrompts
    load_tendering: GelitaLoadTenderingSettings
    workflow_error_alerts: WorkflowErrorAlertSettings | None = None

    @model_validator(mode="after")
    def _require_carrier_ack_prompt(self) -> GelitaTenantSettings:
        ref = (self.prompts.load_tendering.carrier_ack or "").strip()
        if not ref:
            raise ValueError("prompts.load_tendering.carrier_ack must be non-empty")
        return self

    def branch_for_load_type(self, load_type: str | None) -> GelitaLoadTypeBranch:
        bucket: Literal["ltl", "ftl"] = (
            "ftl" if str(load_type or "").strip().upper() == "FTL" else "ltl"
        )
        return getattr(self.load_tendering, bucket)
