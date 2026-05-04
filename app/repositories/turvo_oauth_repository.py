"""Turvo OAuth credentials read/write on ``tenants.config`` (JSON)."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


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


class TurvoOAuthRepository:
    def _load_config(self, app_user_id: str) -> Optional[dict[str, Any]]:
        table = _table()
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT config FROM {table} WHERE app_user_id = %s",
                    (app_user_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return _normalize_config(row[0])

    def _save(self, app_user_id: str, cfg: dict[str, Any]) -> None:
        table = _table()
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET config = %s WHERE app_user_id = %s",
                    (Json(cfg), app_user_id),
                )
                if cur.rowcount == 0:
                    raise RuntimeError(
                        f"No {table} row with app_user_id={app_user_id!r}; create tenant first."
                    )
            conn.commit()

    def get_row(self, app_user_id: str) -> Optional[dict[str, Any]]:
        cfg = self._load_config(app_user_id)
        if cfg is None:
            return None
        return _config_to_row(app_user_id, cfg)

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
        cfg = self._load_config(app_user_id)
        if cfg is None:
            raise RuntimeError(
                f"No {_table()} row with app_user_id={app_user_id!r}; create tenant first."
            )
        patch = deepcopy(cfg)
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
        self._save(app_user_id, patch)

    def update_tokens_only(
        self,
        app_user_id: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        cfg = self._load_config(app_user_id)
        if cfg is None:
            raise RuntimeError(
                f"No {_table()} row with app_user_id={app_user_id!r}; create tenant first."
            )
        patch = deepcopy(cfg)
        patch["access_token"] = access_token
        if refresh_token is not None:
            patch["refresh_token"] = refresh_token
        if token_type is not None:
            patch["token_type"] = token_type
        if access_token_expires_at is not None:
            patch["access_token_expires_at"] = access_token_expires_at.isoformat()
        patch["token_updated_at"] = _now_iso()
        self._save(app_user_id, patch)

    def has_user(self, app_user_id: str) -> bool:
        cfg = self._load_config(app_user_id)
        if cfg is None:
            return False
        return _config_to_row(app_user_id, cfg) is not None
