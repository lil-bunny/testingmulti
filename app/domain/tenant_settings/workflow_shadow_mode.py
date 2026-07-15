"""Parse per-workflow ``shadow_mode`` from ``tenants.settings``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from app.domain.tenant_settings.email_recipients import EmailRecipients

ShadowCapableWorkflow = Literal["driver_assignment", "pod_lifecycle"]

_WORKFLOW_SETTINGS_KEYS: dict[str, str] = {
    "driver_assignment": "driver_assignment",
    "pod_lifecycle": "pod_lifecycle",
}


@dataclass(frozen=True)
class ShadowBypassLoadEntry:
    load_id: str | None = None
    shipment_id: str | None = None


# ponytail: legacy alias until callers migrate
ShadowLiveLoadEntry = ShadowBypassLoadEntry


def _strip_id(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _workflow_settings_block(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> dict[str, Any] | None:
    block_key = _WORKFLOW_SETTINGS_KEYS.get((workflow_name or "").strip())
    if block_key is None or not isinstance(tenant_settings, dict):
        return None
    block = tenant_settings.get(block_key)
    if not isinstance(block, dict):
        return None
    return block


def workflow_shadow_mode_enabled(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> bool:
    """True when the workflow block has ``shadow_mode: true``."""
    block = _workflow_settings_block(tenant_settings, workflow_name=workflow_name)
    if block is None:
        return False
    return bool(block.get("shadow_mode"))


def _shadow_bypass_loads_raw_list(block: dict[str, Any]) -> list[Any] | None:
    raw_list = block.get("shadow_bypass_loads")
    if isinstance(raw_list, list):
        return raw_list
    legacy = block.get("shadow_live_loads")
    if isinstance(legacy, list):
        return legacy
    return None


def _parse_shadow_bypass_load_entry(raw: Any) -> ShadowBypassLoadEntry | None:
    if not isinstance(raw, dict):
        return None
    load_id = _strip_id(raw.get("load_id"))
    shipment_id = _strip_id(raw.get("shipment_id"))
    if not load_id and not shipment_id:
        return None
    return ShadowBypassLoadEntry(
        load_id=load_id or None,
        shipment_id=shipment_id or None,
    )


def parse_shadow_bypass_loads(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> tuple[ShadowBypassLoadEntry, ...]:
    """Read validated ``shadow_bypass_loads`` entries from the workflow settings block."""
    block = _workflow_settings_block(tenant_settings, workflow_name=workflow_name)
    if block is None:
        return ()
    raw_list = _shadow_bypass_loads_raw_list(block)
    if raw_list is None:
        return ()
    entries: list[ShadowBypassLoadEntry] = []
    for item in raw_list:
        parsed = _parse_shadow_bypass_load_entry(item)
        if parsed is not None:
            entries.append(parsed)
    return tuple(entries)


parse_shadow_live_loads = parse_shadow_bypass_loads


def load_in_shadow_bypass_allowlist(
    tenant_settings: dict[str, Any] | None,
    state_data: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> bool:
    """True when run ``load_id`` or ``shipment_id`` matches any configured bypass entry."""
    entries = parse_shadow_bypass_loads(tenant_settings, workflow_name=workflow_name)
    if not entries:
        return False

    run_load_id = ""
    run_shipment_id = ""
    if isinstance(state_data, dict):
        run_load_id = _strip_id(state_data.get("load_id"))
        run_shipment_id = _strip_id(state_data.get("shipment_id"))

    for entry in entries:
        if entry.load_id and entry.load_id == run_load_id:
            return True
        if entry.shipment_id and entry.shipment_id == run_shipment_id:
            return True
    return False


def workflow_shadow_active(
    tenant_settings: dict[str, Any] | None,
    state_data: dict[str, Any] | None = None,
    *,
    workflow_name: str,
) -> bool:
    """True when shadow mode is on via injected state flag or tenant settings."""
    shadow_on = False
    if isinstance(state_data, dict) and state_data.get("workflow_shadow_mode"):
        shadow_on = True
    elif workflow_shadow_mode_enabled(tenant_settings, workflow_name=workflow_name):
        shadow_on = True

    if not shadow_on:
        return False

    if load_in_shadow_bypass_allowlist(
        tenant_settings,
        state_data,
        workflow_name=workflow_name,
    ):
        return False

    return True


load_in_shadow_live_allowlist = load_in_shadow_bypass_allowlist


def shadow_metadata_patch(state_data: dict[str, Any] | None) -> dict[str, Any]:
    """Activity metadata fragment when the run is in workflow shadow mode."""
    if not isinstance(state_data, dict):
        return {}
    tenant_settings = (
        state_data.get("tenant_settings")
        if isinstance(state_data.get("tenant_settings"), dict)
        else None
    )
    workflow_name = str(state_data.get("workflow_name") or "").strip()
    if workflow_name and workflow_shadow_active(
        tenant_settings,
        state_data,
        workflow_name=workflow_name,
    ):
        return {"workflow_shadow_mode": True}
    if state_data.get("workflow_shadow_mode") and not workflow_name:
        return {"workflow_shadow_mode": True}
    return {}


def parse_shadow_mail_recipients(
    tenant_settings: dict[str, Any] | None,
    *,
    workflow_name: str,
) -> EmailRecipients | None:
    """Return redirect recipients when the workflow block has validated ``shadow_emails.to``."""
    block = _workflow_settings_block(tenant_settings, workflow_name=workflow_name)
    if block is None:
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
