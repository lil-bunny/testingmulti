"""Parse ``tenants.settings`` JSON into tenant-specific Pydantic models."""

from __future__ import annotations

from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.domain.tenant_settings.gelita import GelitaTenantSettings

TSettings = TypeVar("TSettings", bound=BaseModel)

_TENANT_SETTINGS_MODELS: dict[str, type[BaseModel]] = {
    "gelita": GelitaTenantSettings,
}


def registered_tenant_settings_slugs() -> frozenset[str]:
    return frozenset(_TENANT_SETTINGS_MODELS)


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


def parse_tenant_settings_or_none(slug: str, raw: Any) -> BaseModel | None:
    """Like ``parse_tenant_settings`` but returns ``None`` on validation failure (logs at call site)."""
    try:
        return parse_tenant_settings(slug, raw)
    except ValidationError:
        return None


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
