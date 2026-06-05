"""Per-tenant Turvo Public API OAuth: password grant, refresh, persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.core.at_rest_secret import decrypt_password, encrypt_password
from app.core.config import settings
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.tenant_settings.tms import TmsSettings
from app.integrations.turvo.oauth_http import TurvoOAuthHttpError, post_token
from app.integrations.turvo.public_api_urls import (
    build_oauth_token_url,
    normalize_turvo_publicapi_url,
)
from app.repositories.turvo_oauth_repository import TurvoOAuthRepository

logger = get_logger(__name__)

_REFRESH_SKEW = timedelta(seconds=60)


def _require_turvo_partner_config(tenant_slug: str, tms: TmsSettings) -> None:
    """Validate tenant ``tms`` partner fields are present (no env fallback)."""
    slug = (tenant_slug or "").strip() or "unknown"
    missing = [
        name
        for name, val in (
            ("public_api_url", tms.public_api_url),
            ("client_id", tms.client_id),
            ("client_secret", tms.client_secret),
            ("x_api_key", tms.x_api_key),
        )
        if not (val and str(val).strip())
    ]
    if missing:
        raise RuntimeError(
            f"Tenant {slug!r} missing tenants.settings.tms partner fields: {missing}"
        )


def _token_url(tms: TmsSettings) -> str:
    base = normalize_turvo_publicapi_url(tms.public_api_url or "")
    return build_oauth_token_url(
        base,
        tms.client_id or "",
        tms.client_secret or "",
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
        self._repo = repository

    def _repo_or(self, repos: Any) -> TurvoOAuthRepository:
        return self._repo or repos.turvo_oauth

    def _get_row(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        if self._repo is not None:
            return self._repo.get_row_by_tenant_slug(tenant_slug)
        return run_with_repos(
            lambda repos: self._repo_or(repos).get_row_by_tenant_slug(tenant_slug)
        )

    def has_oauth(self, tenant_slug: str) -> bool:
        if self._repo is not None:
            return self._repo.has_oauth(tenant_slug)
        return run_with_repos(
            lambda repos: self._repo_or(repos).has_oauth(tenant_slug)
        )

    def has_tms_partner_config(self, tenant_slug: str) -> bool:
        if self._repo is not None:
            return self._repo.has_tms_partner_config(tenant_slug)
        return run_with_repos(
            lambda repos: self._repo_or(repos).has_tms_partner_config(tenant_slug)
        )

    def _load_tms(self, tenant_slug: str) -> TmsSettings:
        if self._repo is not None:
            return self._repo.get_tms_settings(tenant_slug)
        return run_with_repos(
            lambda repos: self._repo_or(repos).get_tms_settings(tenant_slug)
        )

    async def authenticate_tenant(
        self,
        tenant_slug: str,
        turvo_username: str,
        turvo_password: str,
    ) -> dict[str, Any]:
        tms = await asyncio.to_thread(self._load_tms, tenant_slug)
        _require_turvo_partner_config(tenant_slug, tms)
        key = settings.TURVO_OAUTH_ENCRYPTION_KEY
        ciphertext = encrypt_password(turvo_password, key)
        url = _token_url(tms)
        body: dict[str, Any] = {
            "grant_type": "password",
            "username": turvo_username,
            "password": turvo_password,
        }
        data = await post_token(url, body, tms.x_api_key)
        expires_at = _expires_at_from_token_response(data)

        def persist() -> None:
            if self._repo is not None:
                self._repo.upsert_oauth(
                    tenant_slug,
                    turvo_username,
                    ciphertext,
                    data["access_token"],
                    data.get("refresh_token"),
                    data.get("token_type"),
                    expires_at,
                )
            else:
                run_with_repos(
                    lambda repos: self._repo_or(repos).upsert_oauth(
                        tenant_slug,
                        turvo_username,
                        ciphertext,
                        data["access_token"],
                        data.get("refresh_token"),
                        data.get("token_type"),
                        expires_at,
                    )
                )

        await asyncio.to_thread(persist)
        return {
            "success": True,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type"),
        }

    async def refresh_tenant_token(self, tenant_slug: str) -> dict[str, Any]:
        key = settings.TURVO_OAUTH_ENCRYPTION_KEY

        def load():
            tms_cfg = self._load_tms(tenant_slug)
            row = self._get_row(tenant_slug)
            return tms_cfg, row

        tms, row = await asyncio.to_thread(load)
        _require_turvo_partner_config(tenant_slug, tms)
        if not row:
            raise ValueError(f"No Turvo credentials stored for tenant {tenant_slug!r}")

        url = _token_url(tms)
        x_key = tms.x_api_key
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
                    "Turvo refresh failed (%s), falling back to password grant for tenant %s",
                    e.status_code,
                    tenant_slug,
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

        def persist() -> None:
            if self._repo is not None:
                self._repo.update_tokens_only(
                    tenant_slug,
                    data["access_token"],
                    new_refresh,
                    data.get("token_type"),
                    expires_at,
                )
            else:
                run_with_repos(
                    lambda repos: self._repo_or(repos).update_tokens_only(
                        tenant_slug,
                        data["access_token"],
                        new_refresh,
                        data.get("token_type"),
                        expires_at,
                    )
                )

        await asyncio.to_thread(persist)
        return {
            "success": True,
            "expires_in": data.get("expires_in"),
            "token_type": data.get("token_type"),
        }

    async def get_tenant_tokens(
        self,
        tenant_slug: str,
        proactive_refresh: bool = True,
    ) -> Optional[dict[str, Any]]:
        """Return current tokens for server-side Turvo API calls, or None if not linked."""

        row = await asyncio.to_thread(self._get_row, tenant_slug)
        if not row:
            return None

        if not row.get("access_token") and (
            row.get("refresh_token") or row.get("turvo_password_ciphertext")
        ):
            try:
                await self.refresh_tenant_token(tenant_slug)
            except (TurvoOAuthHttpError, ValueError, RuntimeError) as e:
                logger.warning("Could not refresh missing access token: %s", e)
            row = await asyncio.to_thread(self._get_row, tenant_slug)
            if not row or not row.get("access_token"):
                return None

        if proactive_refresh and _should_refresh(row.get("access_token_expires_at")):
            try:
                await self.refresh_tenant_token(tenant_slug)
            except (TurvoOAuthHttpError, ValueError, RuntimeError) as e:
                logger.exception("Proactive Turvo token refresh failed: %s", e)
            row = await asyncio.to_thread(self._get_row, tenant_slug)
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
