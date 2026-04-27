"""Persistence for per-app-user Turvo OAuth credentials and tokens."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import psycopg

from app.core.config import settings


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


class TurvoOAuthRepository:
    TABLE = "turvo_user_oauth"

    def get_row(self, app_user_id: str) -> Optional[dict[str, Any]]:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT app_user_id, turvo_username, turvo_password_ciphertext,
                           access_token, refresh_token, token_type, access_token_expires_at
                    FROM {self.TABLE}
                    WHERE app_user_id = %s
                    """,
                    (app_user_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "app_user_id": row[0],
                    "turvo_username": row[1],
                    "turvo_password_ciphertext": row[2],
                    "access_token": row[3],
                    "refresh_token": row[4],
                    "token_type": row[5],
                    "access_token_expires_at": row[6],
                }

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
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE} (
                        app_user_id, turvo_username, turvo_password_ciphertext,
                        access_token, refresh_token, token_type, access_token_expires_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (app_user_id) DO UPDATE SET
                        turvo_username = EXCLUDED.turvo_username,
                        turvo_password_ciphertext = EXCLUDED.turvo_password_ciphertext,
                        access_token = EXCLUDED.access_token,
                        refresh_token = COALESCE(EXCLUDED.refresh_token, {self.TABLE}.refresh_token),
                        token_type = EXCLUDED.token_type,
                        access_token_expires_at = EXCLUDED.access_token_expires_at,
                        updated_at = NOW()
                    """,
                    (
                        app_user_id,
                        turvo_username,
                        turvo_password_ciphertext,
                        access_token,
                        refresh_token,
                        token_type,
                        access_token_expires_at,
                    ),
                )
            conn.commit()

    def update_tokens_only(
        self,
        app_user_id: str,
        access_token: str,
        refresh_token: Optional[str],
        token_type: Optional[str],
        access_token_expires_at: Optional[datetime],
    ) -> None:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self.TABLE}
                    SET access_token = %s,
                        refresh_token = COALESCE(%s, refresh_token),
                        token_type = %s,
                        access_token_expires_at = %s,
                        updated_at = NOW()
                    WHERE app_user_id = %s
                    """,
                    (
                        access_token,
                        refresh_token,
                        token_type,
                        access_token_expires_at,
                        app_user_id,
                    ),
                )
            conn.commit()

    def has_user(self, app_user_id: str) -> bool:
        with _conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT 1 FROM {self.TABLE} WHERE app_user_id = %s",
                    (app_user_id,),
                )
                return cur.fetchone() is not None
