"""Parse ``tenants.settings`` JSON into tenant-specific Pydantic models."""

from __future__ import annotations

import copy
from typing import Any, TypeVar

from pydantic import BaseModel

from app.domain.tenant_settings.gelita import GelitaTenantSettings
from app.domain.tenant_settings.t3ra import T3raTenantSettings
from app.models.tenants import TenantSlug

TSettings = TypeVar("TSettings", bound=BaseModel)

_TENANT_SETTINGS_MODELS: dict[str, type[BaseModel]] = {
    TenantSlug.GELITA: GelitaTenantSettings,
    TenantSlug.T3RA: T3raTenantSettings,
}


def parse_tenant_settings(slug: str, raw: Any) -> BaseModel | None:
    """
    Validate raw ``tenants.settings`` for a known tenant slug.

    Returns ``None`` when the slug has no registered model (callers keep using raw dict).
    Raises ``ValidationError`` when JSON does not match the tenant contract.
    """
    model_cls = _TENANT_SETTINGS_MODELS.get((slug or "").strip().lower())
    if model_cls is None:
        return None
    if not isinstance(raw, dict):
        raw = {}
    return model_cls.model_validate(raw)


def normalize_tenant_settings_dict(slug: str, raw: Any) -> dict[str, Any]:
    """
    Return settings for workflow payloads: validated + normalized for registered slugs,
    otherwise the raw dict unchanged.
    """
    if not isinstance(raw, dict):
        raw = {}
    parsed = parse_tenant_settings(slug, raw)
    if parsed is not None:
        dumped = parsed.model_dump(mode="python")
        return dumped if isinstance(dumped, dict) else raw
    return raw


_SECRET_SETTING_PATHS: tuple[tuple[str, ...], ...] = (
    ("tms", "client_secret"),
    ("tms", "x_api_key"),
    ("tms", "access_token"),
    ("tms", "refresh_token"),
    ("tms", "password_ciphertext"),
    ("tms", "user_name"),
    ("ascend", "password_ciphertext"),
    ("ascend", "access_token"),
)


def _remove_secret_setting_paths(settings: dict[str, Any]) -> None:
    for path in _SECRET_SETTING_PATHS:
        node = settings
        for key in path[:-1]:
            child = node.get(key)
            if not isinstance(child, dict):
                break
            node = child
        else:
            if isinstance(node, dict):
                node.pop(path[-1], None)


_APPOINTMENT_SCHEDULING_WORKFLOW_SETTING_KEYS: tuple[str, ...] = (
    "mikey_account_id",
    "appointment_scheduling",
)


def _project_settings_for_workflow(
    workflow_name: str | None,
    settings: dict[str, Any],
) -> dict[str, Any]:
    wf = (workflow_name or "").strip()
    if wf != "appointment_scheduling":
        return settings
    projected: dict[str, Any] = {}
    for key in _APPOINTMENT_SCHEDULING_WORKFLOW_SETTING_KEYS:
        if key in settings:
            projected[key] = copy.deepcopy(settings[key])
    prompts = settings.get("prompts")
    if isinstance(prompts, dict):
        appt_prompts = prompts.get("appointment_scheduling")
        if appt_prompts is not None:
            projected["prompts"] = {
                "appointment_scheduling": copy.deepcopy(appt_prompts),
            }
    return projected


def tenant_settings_for_workflow_state(
    slug: str,
    raw: Any,
    *,
    workflow_name: str | None = None,
) -> dict[str, Any]:
    """
    Validated tenant settings safe for Celery payloads and LangGraph checkpoints.

    Strips credentials (TMS secrets, Ascend password). For ``appointment_scheduling``,
    keeps only mikey, appointment_scheduling config, and appointment prompts.
    Other workflows keep the full normalized settings (minus secrets).
    """
    normalized = normalize_tenant_settings_dict(slug, raw)
    if not isinstance(normalized, dict):
        return {}
    projected = copy.deepcopy(normalized)
    _remove_secret_setting_paths(projected)
    return _project_settings_for_workflow(workflow_name, projected)
