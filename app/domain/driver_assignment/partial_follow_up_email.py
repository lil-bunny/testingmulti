"""Tenant ``driver_assignment.partial_follow_up_email`` config."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML = (
    "<html><body>"
    "<p>Thanks for your reply.</p>"
    "<p>We still need <strong>complete driver details</strong> for this load.</p>"
    "<p>Please reply with the driver&apos;s <strong>full name</strong> and "
    "<strong>mobile number</strong> (or email address).</p>"
    "<p>If you already sent this, please reply again with both in one message.</p>"
    "</body></html>"
)


class DriverAssignmentPartialFollowUpEmailConfig(BaseModel):
    """Optional HTML for insufficient driver-details chase mail."""

    model_config = ConfigDict(extra="ignore")

    template_html: str | None = None

    def body_html(self) -> str:
        text = str(self.template_html or "").strip()
        return text or DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML


def parse_driver_assignment_partial_follow_up_email(
    tenant_settings: dict[str, Any] | None,
) -> DriverAssignmentPartialFollowUpEmailConfig | None:
    if not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get("driver_assignment")
    if not isinstance(block, dict):
        return None
    raw = block.get("partial_follow_up_email")
    if not isinstance(raw, dict):
        return None
    try:
        return DriverAssignmentPartialFollowUpEmailConfig.model_validate(raw)
    except Exception:
        return None


def resolve_partial_follow_up_email(
    tenant_settings: dict[str, Any] | None,
) -> str:
    """Return body HTML for partial follow-up sends."""
    cfg = parse_driver_assignment_partial_follow_up_email(tenant_settings)
    if cfg is None:
        return DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML
    return cfg.body_html()


__all__ = (
    "DEFAULT_PARTIAL_DRIVER_DETAILS_FOLLOW_UP_HTML",
    "DriverAssignmentPartialFollowUpEmailConfig",
    "parse_driver_assignment_partial_follow_up_email",
    "resolve_partial_follow_up_email",
)
