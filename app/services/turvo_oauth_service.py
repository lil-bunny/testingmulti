"""Per-user Turvo Public API OAuth: password grant, refresh, persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.at_rest_secret import decrypt_password, encrypt_password
from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.oauth_http import TurvoOAuthHttpError, post_token
from app.integrations.turvo.public_api_urls import (
    build_oauth_token_url,
    normalize_turvo_publicapi_url,
)
from app.repositories.turvo_oauth_repository import TurvoOAuthRepository

logger = get_logger(__name__)

_REFRESH_SKEW = timedelta(seconds=60)


def _require_turvo_config() -> None:
    if not (
        settings.TURVO_PUBLICAPI_URL
        and settings.TURVO_PUBLICAPI_CLIENT_ID
        and settings.TURVO_PUBLICAPI_CLIENT_SECRET
    ):
        raise RuntimeError("Turvo Public API env is not fully configured")


def _token_url() -> str:
    base = normalize_turvo_publicapi_url(settings.TURVO_PUBLICAPI_URL or "")
    return build_oauth_token_url(
        base,
        settings.TURVO_PUBLICAPI_CLIENT_ID or "",
        settings.TURVO_PUBLICAPI_CLIENT_SECRET or "",
    )


def _expires_at_from_token_response(data: dict[str, Any]) -> Optional[datetime]:
    ei = data.get("expires_in")
    if ei is None:
        return None
    try:
        sec = int(ei)
    except (TypeError, ValueError):
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=sec)


class TurvoOAuthService:
    def __init__(self, repository: Optional[TurvoOAuthRepository] = None):
        self._repo = repository or TurvoOAuthRepository()

    async def authenticate_user(
        self,
        app_user_id: str,
        turvo_username: str,
        turvo_password: str,
    ) -> dict[str, Any]:
        _require_turvo_config()
        key = settings.TURVO_OAUTH_ENCRYPTION_KEY
        ciphertext = encrypt_password(turvo_password, key)
        url = _token_url()
        body: dict[str, Any] = {
            "grant_type": "password",
            "username": turvo_username,
            "password": turvo_password,
        }
        data = await post_token(url, body, settings.TURVO_X_API_KEY)
        expires_at = _expires_at_from_token_response(data)
        await asyncio.to_thread(
            self._repo.upsert_user_oauth,
            app_user_id,
            turvo_username,
            ciphertext,
            data["access_token"],
            data.get("refresh_token"),
            data.get("token_type"),
            expires_at,
        )
        return {
            "success": True,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type"),
        }

    async def refresh_user_token(self, app_user_id: str) -> dict[str, Any]:
        _require_turvo_config()
        key = settings.TURVO_OAUTH_ENCRYPTION_KEY

        def load():
            return self._repo.get_row(app_user_id)

        row = await asyncio.to_thread(load)
        if not row:
            raise ValueError("No Turvo credentials stored for this user")

        url = _token_url()
        x_key = settings.TURVO_X_API_KEY
        plain = decrypt_password(row["turvo_password_ciphertext"], key)

        data: Optional[dict[str, Any]] = None
        if row.get("refresh_token"):
            try:
                data = await post_token(
                    url,
                    {
                        "grant_type": "refresh_token",
                        "refresh_token": row["refresh_token"],
                    },
                    x_key,
                )
            except TurvoOAuthHttpError as e:
                logger.info(
                    "Turvo refresh failed (%s), falling back to password grant for user %s",
                    e.status_code,
                    app_user_id,
                )
                data = None

        if data is None:
            data = await post_token(
                url,
                {
                    "grant_type": "password",
                    "username": row["turvo_username"],
                    "password": plain,
                },
                x_key,
            )

        expires_at = _expires_at_from_token_response(data)
        new_refresh = data.get("refresh_token")
        if new_refresh is None:
            new_refresh = row.get("refresh_token")

        def persist():
            self._repo.update_tokens_only(
                app_user_id,
                data["access_token"],
                new_refresh,
                data.get("token_type"),
                expires_at,
            )

        await asyncio.to_thread(persist)
        return {
            "success": True,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type"),
        }

    async def get_user_tokens(
        self, app_user_id: str, proactive_refresh: bool = True
    ) -> Optional[dict[str, Any]]:
        """Return current tokens for server-side Turvo API calls, or None if not linked."""
        _require_turvo_config()
        key = settings.TURVO_OAUTH_ENCRYPTION_KEY

        def load():
            return self._repo.get_row(app_user_id)

        row = await asyncio.to_thread(load)
        if not row:
            return None

        if not row.get("access_token") and (
            row.get("refresh_token") or row.get("turvo_password_ciphertext")
        ):
            try:
                await self.refresh_user_token(app_user_id)
            except (TurvoOAuthHttpError, ValueError) as e:
                logger.warning("Could not refresh missing access token: %s", e)
            row = await asyncio.to_thread(load)
            if not row or not row.get("access_token"):
                return None

        if proactive_refresh and _should_refresh(row.get("access_token_expires_at")):
            try:
                await self.refresh_user_token(app_user_id)
            except (TurvoOAuthHttpError, ValueError) as e:
                logger.exception("Proactive Turvo token refresh failed: %s", e)
            row = await asyncio.to_thread(load)
            if not row:
                return None

        return {
            "access_token": row.get("access_token"),
            "refresh_token": row.get("refresh_token"),
            "token_type": row.get("token_type"),
            "access_token_expires_at": row.get("access_token_expires_at"),
        }


def _should_refresh(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at - _REFRESH_SKEW <= datetime.now(timezone.utc)
