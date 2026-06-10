"""Parse ``tenants.settings`` JSON into tenant-specific Pydantic models."""

from __future__ import annotations

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
