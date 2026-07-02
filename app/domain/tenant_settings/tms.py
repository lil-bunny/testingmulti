"""Per-tenant TMS integration settings (``tenants.settings.tms``)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

_LEGACY_AUTH_KEYS: tuple[str, ...] = (
    "user_name",
    "password_ciphertext",
    "access_token",
    "refresh_token",
    "token_type",
    "access_token_expires_at",
    "token_created_at",
    "token_updated_at",
)

_REQUIRED_PARTNER_KEYS: tuple[str, ...] = (
    "public_api_url",
    "client_id",
    "client_secret",
    "x_api_key",
)


class TmsSettings(BaseModel):
    """Turvo (or future TMS) partner + user auth stored under ``tenants.settings.tms``."""

    model_config = ConfigDict(extra="ignore")

    provider: str = "turvo"
    public_api_url: str | None = None
    ui_base_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    x_api_key: str | None = None
    user_name: str | None = None
    password_ciphertext: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    token_type: str | None = None
    access_token_expires_at: str | None = None
    token_created_at: str | None = None
    token_updated_at: str | None = None
    pod_document_lookup_id: str | None = None


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def merge_tms_config(cfg: dict[str, Any]) -> dict[str, Any]:
    """
    Merge ``settings.tms`` with legacy flat root auth keys (migration-only).

    Does not read environment variables.
    """
    merged: dict[str, Any] = dict(cfg.get("tms") or {})
    for key in _LEGACY_AUTH_KEYS:
        if _clean(merged.get(key)):
            continue
        raw = cfg.get(key)
        if raw is not None and _clean(raw):
            merged[key] = raw
    if not _clean(merged.get("provider")):
        merged["provider"] = "turvo"
    return merged


def resolve_tms_settings(tenant_slug: str, cfg: dict[str, Any]) -> TmsSettings:
    """
    Resolve TMS settings for a tenant from ``tenants.settings`` JSON.

    Raises ``ValueError`` when required partner fields are missing.
    """
    slug = (tenant_slug or "").strip() or "unknown"
    merged = merge_tms_config(cfg)
    model = TmsSettings.model_validate(merged)

    missing = [
        key
        for key in _REQUIRED_PARTNER_KEYS
        if not _clean(getattr(model, key))
    ]
    if missing:
        raise ValueError(
            f"Tenant {slug!r} missing required tenants.settings.tms fields: {missing}"
        )
    return model


def has_tms_partner_config(cfg: dict[str, Any]) -> bool:
    """True when ``cfg`` has all required partner fields under ``tms`` (or legacy merge)."""
    try:
        resolve_tms_settings("", cfg)
        return True
    except ValueError:
        return False
