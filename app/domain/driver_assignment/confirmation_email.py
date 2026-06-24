"""Tenant ``driver_assignment.confirmation_email`` config (multi-tenant)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DriverAssignmentConfirmationEmailConfig(BaseModel):
    """
    Generic confirmation email block under ``tenant_settings.driver_assignment``.

    Example (t3ra):
        tracking_customer_names: ["USCS CSC"]
        tracking_template_html: ...FourKites copy...
        default_template_html: ...Turvo app copy...
        send_invite_for_tracking: false
        send_invite_for_default: true
    """

    model_config = ConfigDict(extra="ignore")

    tracking_customer_names: list[str] = Field(default_factory=list)
    tracking_template_html: str | None = None
    default_template_html: str | None = None
    send_invite_for_tracking: bool = False
    send_invite_for_default: bool = True

    @field_validator("tracking_customer_names", mode="before")
    @classmethod
    def _normalize_tracking_names(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            cleaned = value.strip()
            return [cleaned] if cleaned else []
        if isinstance(value, list):
            out: list[str] = []
            for item in value:
                cleaned = str(item).strip()
                if cleaned and cleaned not in out:
                    out.append(cleaned)
            return out
        return []

    @property
    def tracking_customer_name_set(self) -> frozenset[str]:
        return frozenset(self.tracking_customer_names)

    def is_tracking_customer(self, customer_name: str | None) -> bool:
        name = (customer_name or "").strip()
        if not name:
            return False
        return name in self.tracking_customer_name_set

    def template_html_for(self, *, is_tracking_customer: bool) -> str | None:
        raw = (
            self.tracking_template_html
            if is_tracking_customer
            else self.default_template_html
        )
        text = str(raw or "").strip()
        return text or None

    def send_invite_for(self, *, is_tracking_customer: bool) -> bool:
        return (
            self.send_invite_for_tracking
            if is_tracking_customer
            else self.send_invite_for_default
        )

    def variant_key_for(self, *, is_tracking_customer: bool) -> str:
        return "tracking" if is_tracking_customer else "default"


@dataclass(frozen=True)
class ParsedConfirmationEmailRaw:
    """Normalized dict slice after legacy key migration."""

    tracking_customer_names: list[str]
    tracking_template_html: str | None
    default_template_html: str | None
    send_invite_for_tracking: bool
    send_invite_for_default: bool


def _legacy_migration(raw: dict[str, Any]) -> ParsedConfirmationEmailRaw:
    names = raw.get("tracking_customer_names")
    if names is None and raw.get("tracking_customer_name"):
        names = [raw.get("tracking_customer_name")]

    tracking_html = raw.get("tracking_template_html") or raw.get(
        "fourkites_template_html"
    )
    default_html = raw.get("default_template_html") or raw.get(
        "turvo_app_template_html"
    )

    def _bool(key: str, default: bool) -> bool:
        val = raw.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in ("1", "true", "yes")

    return ParsedConfirmationEmailRaw(
        tracking_customer_names=list(names or []),
        tracking_template_html=str(tracking_html).strip() if tracking_html else None,
        default_template_html=str(default_html).strip() if default_html else None,
        send_invite_for_tracking=_bool("send_invite_for_tracking", False),
        send_invite_for_default=_bool("send_invite_for_default", True),
    )


def parse_driver_assignment_confirmation_email(
    tenant_settings: dict[str, Any] | None,
) -> DriverAssignmentConfirmationEmailConfig | None:
    """Read ``driver_assignment.confirmation_email`` from tenant settings."""
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("driver_assignment")
    if not isinstance(block, dict):
        return None
    raw = block.get("confirmation_email")
    if not isinstance(raw, dict):
        return None
    migrated = _legacy_migration(raw)
    try:
        return DriverAssignmentConfirmationEmailConfig.model_validate(
            {
                "tracking_customer_names": migrated.tracking_customer_names,
                "tracking_template_html": migrated.tracking_template_html,
                "default_template_html": migrated.default_template_html,
                "send_invite_for_tracking": migrated.send_invite_for_tracking,
                "send_invite_for_default": migrated.send_invite_for_default,
            }
        )
    except Exception:
        return None


__all__ = (
    "DriverAssignmentConfirmationEmailConfig",
    "parse_driver_assignment_confirmation_email",
)
