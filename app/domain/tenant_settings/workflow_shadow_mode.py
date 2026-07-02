"""Parse per-workflow ``shadow_mode`` from ``tenants.settings``."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ValidationError

from app.domain.tenant_settings.email_recipients import EmailRecipients

ShadowCapableWorkflow = Literal["driver_assignment", "pod_lifecycle"]

_WORKFLOW_SETTINGS_KEYS: dict[str, str] = {
    "driver_assignment": "driver_assignment",
    "pod_lifecycle": "pod_lifecycle",
}


def workflow_shadow_mode_enabled(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> bool:
    """True when the workflow block has ``shadow_mode: true``."""
    block_key = _WORKFLOW_SETTINGS_KEYS.get((workflow_name or "").strip())
    if block_key is None or not isinstance(tenant_settings, dict):
        return False
    block = tenant_settings.get(block_key)
    if not isinstance(block, dict):
        return False
    return bool(block.get("shadow_mode"))


def workflow_shadow_active(
    tenant_settings: dict[str, Any] | None,
    state_data: dict[str, Any] | None = None,
    *,
    workflow_name: str,
) -> bool:
    """True when shadow mode is on via injected state flag or tenant settings."""
    if isinstance(state_data, dict) and state_data.get("workflow_shadow_mode"):
        return True
    return workflow_shadow_mode_enabled(tenant_settings, workflow_name=workflow_name)


def shadow_metadata_patch(state_data: dict[str, Any] | None) -> dict[str, Any]:
    """Activity metadata fragment when the run is in workflow shadow mode."""
    if isinstance(state_data, dict) and state_data.get("workflow_shadow_mode"):
        return {"workflow_shadow_mode": True}
    return {}


def parse_shadow_mail_recipients(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> EmailRecipients | None:
    """Return redirect recipients when the workflow block has validated ``shadow_emails.to``."""
    block_key = _WORKFLOW_SETTINGS_KEYS.get((workflow_name or "").strip())
    if block_key is None or not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get(block_key)
    if not isinstance(block, dict):
        return None
    raw = block.get("shadow_emails")
    if not isinstance(raw, dict):
        return None
    try:
        recipients = EmailRecipients.model_validate(raw)
    except ValidationError:
        return None
    return recipients if recipients.to else None


def shadow_mail_metadata_patch(
    *,
    redirected: bool,
    recipients: EmailRecipients | None = None,
) -> dict[str, Any]:
    if not redirected or recipients is None:
        return {}
    return {
        "shadow_mail_redirect": True,
        "shadow_mail_to": list(recipients.to),
    }
