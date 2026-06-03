"""Turvo OAuth credentials read/write on ``tenants.settings`` (JSON).

Looks up rows where ``settings->>'app_user_id'`` equals the resolved app user id.

If the caller passes an empty id, ``TURVO_DEFAULT_APP_USER_ID`` (env) is used
when set.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings


def _table() -> str:
    t = settings.TENANTS_TABLE.strip()
    return t if t else "tenants"


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


def _config_to_row(app_user_id: str, cfg: dict[str, Any]) -> Optional[dict[str, Any]]:
    uname = cfg.get("user_name")
    pwd = cfg.get("password_ciphertext")
    if not uname and not pwd and not cfg.get("access_token"):
        return None
    return {
        "app_user_id": app_user_id,
        "turvo_username": str(uname or ""),
        "turvo_password_ciphertext": str(pwd or ""),
        "access_token": cfg.get("access_token"),
        "refresh_token": cfg.get("refresh_token"),
        "token_type": cfg.get("token_type"),
        "access_token_expires_at": _parse_expires_at(cfg.get("access_token_expires_at")),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_needle(app_user_id: Optional[str]) -> str:
    stripped = (app_user_id or "").strip()
    if stripped:
        return stripped
    fb = getattr(settings, "TURVO_DEFAULT_APP_USER_ID", None)
    if fb is None:
        return ""
    return str(fb).strip()


_SQL_APP_USER_MATCH = "(settings::jsonb ->> 'app_user_id')"


class TurvoOAuthRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _load_config(self, app_user_id: str) -> Optional[dict[str, Any]]:
        needle = _resolve_needle(app_user_id)
        if not needle:
            return None
        table = _table()
        row = self._session.execute(
            text(
                f"SELECT settings FROM {table} WHERE {_SQL_APP_USER_MATCH} = :needle"
            ),
            {"needle": needle},
        ).first()
        if not row:
            return None
        return _normalize_config(row[0])

    def _save(self, app_user_id: str, cfg: dict[str, Any]) -> None:
        needle = _resolve_needle(app_user_id)
        if not needle:
            raise RuntimeError(
                "Cannot save Turvo OAuth: no app user id (set X-App-User-Id or "
                "TURVO_DEFAULT_APP_USER_ID)"
            )
        table = _table()
        result = self._session.execute(
            text(
                f"UPDATE {table} SET settings = CAST(:settings AS jsonb) "
                f"WHERE {_SQL_APP_USER_MATCH} = :needle"
            ),
            {"settings": cfg, "needle": needle},
        )
        if result.rowcount == 0:
            raise RuntimeError(
                f"No {table} row with settings.app_user_id={needle!r}; create tenant first."
            )

    def get_row(self, app_user_id: str) -> Optional[dict[str, Any]]:
        needle = _resolve_needle(app_user_id)
        if not needle:
            return None
        cfg = self._load_config(app_user_id)
        if cfg is None:
            return None
        display = ((cfg.get("app_user_id") or "").strip()) or needle
        return _config_to_row(display, cfg)

    def upsert_user_oauth(
        self,
        app_user_id: str,
        turvo_username: str,
        turvo_password_ciphertext: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        needle = _resolve_needle(app_user_id)
        cfg = self._load_config(app_user_id)
        if cfg is None:
            raise RuntimeError(
                f"No {_table()} row with settings.app_user_id={needle!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        patch["app_user_id"] = needle
        patch["user_name"] = turvo_username
        patch["password_ciphertext"] = turvo_password_ciphertext
        patch["access_token"] = access_token
        if refresh_token is not None:
            patch["refresh_token"] = refresh_token
        if token_type is not None:
            patch["token_type"] = token_type
        if access_token_expires_at is not None:
            patch["access_token_expires_at"] = access_token_expires_at.isoformat()
        patch["token_updated_at"] = _now_iso()
        if "token_created_at" not in patch:
            patch["token_created_at"] = patch["token_updated_at"]
        self._save(needle, patch)

    def update_tokens_only(
        self,
        app_user_id: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        needle = _resolve_needle(app_user_id)
        cfg = self._load_config(app_user_id)
        if cfg is None:
            raise RuntimeError(
                f"No {_table()} row with settings.app_user_id={needle!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        patch.setdefault("app_user_id", needle)
        patch["access_token"] = access_token
        if refresh_token is not None:
            patch["refresh_token"] = refresh_token
        if token_type is not None:
            patch["token_type"] = token_type
        if access_token_expires_at is not None:
            patch["access_token_expires_at"] = access_token_expires_at.isoformat()
        patch["token_updated_at"] = _now_iso()
        self._save(needle, patch)

    def has_user(self, app_user_id: str) -> bool:
        needle = _resolve_needle(app_user_id)
        if not needle:
            return False
        cfg = self._load_config(app_user_id)
        if cfg is None:
            return False
        resolved = ((cfg.get("app_user_id") or "").strip()) or needle
        return _config_to_row(resolved, cfg) is not None
