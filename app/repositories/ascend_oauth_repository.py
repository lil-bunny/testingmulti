"""Ascend OAuth credentials on ``tenants.settings.ascend``."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

from sqlalchemy import text

from app.core.db import jsonb_param
from app.domain.tenant_settings.ascend import AscendSettings

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _config_to_row(tenant_slug: str, cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    block = cfg.get("ascend")
    if not isinstance(block, dict):
        return None
    ascend = AscendSettings.model_validate(block)
    email = str(ascend.email or "").strip()
    pwd = str(ascend.password_ciphertext or "").strip()
    if not email or not pwd:
        return None
    return {
        "tenant_slug": tenant_slug,
        "email": email,
        "password_ciphertext": pwd,
        "access_token": ascend.access_token,
        "access_token_expires_at": _parse_expires_at(ascend.access_token_expires_at),
    }


class AscendOAuthRepository:
    TABLE_NAME = "tenants"

    def __init__(self, session: Session) -> None:
        self._session = session

    def _load_config_by_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        slug = (tenant_slug or "").strip()
        if not slug:
            return None
        row = self._session.execute(
            text(f"SELECT settings FROM {self.TABLE_NAME} WHERE slug = :slug"),
            {"slug": slug},
        ).first()
        if not row:
            return None
        return _normalize_config(row[0])

    def _save_by_slug(self, tenant_slug: str, cfg: dict[str, Any]) -> None:
        slug = (tenant_slug or "").strip()
        if not slug:
            raise RuntimeError("Cannot save Ascend OAuth: tenant_slug is required")
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

    def load_config_by_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        return self._load_config_by_slug(tenant_slug)

    def get_row_by_tenant_slug(self, tenant_slug: str) -> Optional[dict[str, Any]]:
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
        *,
        email: str,
        password_ciphertext: str,
        access_token: str,
        access_token_expires_at: Optional[datetime],
    ) -> None:
        slug = (tenant_slug or "").strip()
        cfg = self._load_config_by_slug(slug)
        if cfg is None:
            raise RuntimeError(
                f"No {self.TABLE_NAME} row with slug={slug!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        ascend = dict(patch.get("ascend") or {})
        ascend["email"] = email
        ascend["password_ciphertext"] = password_ciphertext
        ascend["access_token"] = access_token
        if access_token_expires_at is not None:
            ascend["access_token_expires_at"] = access_token_expires_at.isoformat()
        ascend["token_updated_at"] = _now_iso()
        patch["ascend"] = ascend
        self._save_by_slug(slug, patch)
