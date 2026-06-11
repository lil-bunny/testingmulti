"""Parse ``enabledProcesses`` from ``tenants.settings`` JSONB."""

from __future__ import annotations

from typing import Any

DEFAULT_SETTINGS: dict[str, Any] = {"enabledProcesses": ["load_tendering"]}


def enabled_processes_from_settings(settings: dict[str, Any] | None) -> list[str]:
    if not settings:
        return list(DEFAULT_SETTINGS["enabledProcesses"])
    raw = settings.get("enabledProcesses")
    if not isinstance(raw, list):
        return []
    return [str(item) for item in raw if str(item).strip()]
