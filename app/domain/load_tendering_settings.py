"""Read ``load_tendering`` action config from workflow state / Celery payload."""

from __future__ import annotations

from typing import Any

LOAD_TENDERING_SETTINGS_KEY = "load_tendering"


def tenant_settings_root(state_or_data: Any) -> dict[str, Any]:
    """
    Return parsed ``tenant_settings`` from a ``WorkflowState``-like object or payload dict.

    Supports ``state.data``, plain dict payloads, and objects with a ``data`` attribute.
    """
    if isinstance(state_or_data, dict):
        raw = state_or_data.get("tenant_settings")
    else:
        data = getattr(state_or_data, "data", None)
        if isinstance(data, dict):
            raw = data.get("tenant_settings")
        else:
            raw = None
    if isinstance(raw, dict):
        return raw
    return {}


def load_tendering_settings_root(state_or_data: Any) -> dict[str, Any]:
    """Return the ``load_tendering`` subtree of ``tenant_settings``."""
    root = tenant_settings_root(state_or_data)
    block = root.get(LOAD_TENDERING_SETTINGS_KEY)
    if isinstance(block, dict):
        return block
    return {}


def action_settings(state_or_data: Any, action: str) -> dict[str, Any]:
    """
    Return config for one load-tendering action (node name), e.g. ``tender_calculate``.

    Keys match ``tenants.settings.load_tendering.<action>`` in the DB JSON.
    """
    lt = load_tendering_settings_root(state_or_data)
    block = lt.get(action)
    if isinstance(block, dict):
        return block
    return {}
