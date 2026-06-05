"""Turvo OAuth credentials read/write on ``tenants.settings`` (JSON).

All load/save operations key off ``tenants.slug`` (one Turvo login per tenant row).
Partner + user auth are stored under ``settings.tms``.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import jsonb_param
from app.domain.tenant_settings.tms import (
    TmsSettings,
    has_tms_partner_config,
    merge_tms_config,
    resolve_tms_settings,
)

_LEGACY_ROOT_AUTH_KEYS: tuple[str, ...] = (
    "user_name",
    "password_ciphertext",
    "access_token",
    "refresh_token",
    "token_type",
    "access_token_expires_at",
    "token_created_at",
    "token_updated_at",
)


def _normalize_config(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str):
        try:
            out = json.loads(raw)
            return dict(out) if isinstance(out, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _parse_expires_at(val: Any) -> Optional[datetime]:
    if val is None:
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    return None


def _config_to_row(tenant_slug: str, cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    merged = merge_tms_config(cfg)
    uname = merged.get("user_name")
    pwd = merged.get("password_ciphertext")
    if not uname and not pwd and not merged.get("access_token"):
        return None
    return {
        "tenant_slug": tenant_slug,
        "turvo_username": str(uname or ""),
        "turvo_password_ciphertext": str(pwd or ""),
        "access_token": merged.get("access_token"),
        "refresh_token": merged.get("refresh_token"),
        "token_type": merged.get("token_type"),
        "access_token_expires_at": _parse_expires_at(
            merged.get("access_token_expires_at")
        ),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _strip_legacy_root_auth(patch: dict[str, Any]) -> None:
    for key in _LEGACY_ROOT_AUTH_KEYS:
        patch.pop(key, None)


def _ensure_tms_block(patch: dict[str, Any]) -> dict[str, Any]:
    tms = dict(patch.get("tms") or {})
    if not str(tms.get("provider") or "").strip():
        tms["provider"] = "turvo"
    patch["tms"] = tms
    return tms


class TurvoOAuthRepository:
    TABLE_NAME = "tenants"

    def __init__(self, session: Session) -> None:
        self._session = session

    def load_config_by_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        return self._load_config_by_slug(tenant_slug)

    def _load_config_by_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        slug = (tenant_slug or "").strip()
        if not slug:
            return None
        row = self._session.execute(
            text(
                f"SELECT settings FROM {self.TABLE_NAME} WHERE slug = :slug"
            ),
            {"slug": slug},
        ).first()
        if not row:
            return None
        return _normalize_config(row[0])

    def _save_by_slug(self, tenant_slug: str, cfg: dict[str, Any]) -> None:
        slug = (tenant_slug or "").strip()
        if not slug:
            raise RuntimeError("Cannot save Turvo OAuth: tenant_slug is required")
        result = self._session.execute(
            text(
                f"UPDATE {self.TABLE_NAME} SET settings = CAST(:settings AS jsonb) "
                f"WHERE slug = :slug"
            ),
            {"settings": jsonb_param(cfg), "slug": slug},
        )
        if result.rowcount == 0:
            raise RuntimeError(
                f"No {self.TABLE_NAME} row with slug={slug!r}; create tenant first."
            )

    def get_tms_settings(self, tenant_slug: str) -> TmsSettings:
        """Load and validate partner TMS config for a tenant (no env fallback)."""
        slug = (tenant_slug or "").strip()
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            raise ValueError(f"No tenant settings row for slug={slug!r}")
        return resolve_tms_settings(slug, cfg)

    def has_tms_partner_config(self, tenant_slug: str) -> bool:
        slug = (tenant_slug or "").strip()
        if not slug:
            return False
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            return False
        return has_tms_partner_config(cfg)

    def get_row_by_tenant_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        """Load Turvo OAuth material from ``tenants.settings`` for ``tenants.slug``."""
        slug = (tenant_slug or "").strip()
        if not slug:
            return None
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            return None
        return _config_to_row(slug, cfg)

    def upsert_oauth(
        self,
        tenant_slug: str,
        turvo_username: str,
        turvo_password_ciphertext: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        slug = (tenant_slug or "").strip()
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            raise RuntimeError(
                f"No {self.TABLE_NAME} row with slug={slug!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        tms = _ensure_tms_block(patch)
        tms["user_name"] = turvo_username
        tms["password_ciphertext"] = turvo_password_ciphertext
        tms["access_token"] = access_token
        if refresh_token is not None:
            tms["refresh_token"] = refresh_token
        if token_type is not None:
            tms["token_type"] = token_type
        if access_token_expires_at is not None:
            tms["access_token_expires_at"] = access_token_expires_at.isoformat()
        tms["token_updated_at"] = _now_iso()
        if not tms.get("token_created_at"):
            tms["token_created_at"] = tms["token_updated_at"]
        _strip_legacy_root_auth(patch)
        self._save_by_slug(slug, patch)

    def update_tokens_only(
        self,
        tenant_slug: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        slug = (tenant_slug or "").strip()
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            raise RuntimeError(
                f"No {self.TABLE_NAME} row with slug={slug!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        tms = _ensure_tms_block(patch)
        tms["access_token"] = access_token
        if refresh_token is not None:
            tms["refresh_token"] = refresh_token
        if token_type is not None:
            tms["token_type"] = token_type
        if access_token_expires_at is not None:
            tms["access_token_expires_at"] = access_token_expires_at.isoformat()
        tms["token_updated_at"] = _now_iso()
        _strip_legacy_root_auth(patch)
        self._save_by_slug(slug, patch)

    def has_oauth(self, tenant_slug: str) -> bool:
        slug = (tenant_slug or "").strip()
        if not slug:
            return False
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            return False
        return _config_to_row(slug, cfg) is not None
