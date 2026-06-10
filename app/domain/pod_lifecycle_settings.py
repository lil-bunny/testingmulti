"""Read POD lifecycle config from workflow state / Celery payload."""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.domain.load_tendering_settings import tenant_settings_root
from app.domain.state import workflow_state_data

MIKEY_ACCOUNT_ID_KEY = "mikey_account_id"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def mikey_account_id_from_tenant_settings(state_or_data: Any) -> str | None:
    """Unipile sender account for T3RA POD mail (``tenants.settings`` root)."""
    root = tenant_settings_root(state_or_data)
    return _clean(root.get(MIKEY_ACCOUNT_ID_KEY))


def resolve_pod_sender_account_id(state_or_data: Any) -> str | None:
    """
    Resolve Unipile ``account_id`` for POD send/fetch.

    Precedence: explicit payload ``account_id`` → ``mikey_account_id`` → env fallback.
    """
    data = workflow_state_data(state_or_data)
    explicit = _clean(data.get("account_id"))
    if explicit:
        return explicit

    from_tenant = mikey_account_id_from_tenant_settings(state_or_data)
    if from_tenant:
        return from_tenant

    return _clean(settings.UNIPILE_ACCOUNT_ID)


def hydrate_pod_account_id(data: dict[str, Any]) -> None:
    """Set ``account_id`` on reminder/workflow payload when absent."""
    if _clean(data.get("account_id")):
        return
    resolved = resolve_pod_sender_account_id(data)
    if resolved:
        data["account_id"] = resolved
