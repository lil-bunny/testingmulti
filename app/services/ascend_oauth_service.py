"""Per-tenant Ascend API login and token reuse (``tenants.settings.ascend``)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, TYPE_CHECKING

from app.core.at_rest_secret import decrypt_password, encrypt_password
from app.core.config import settings
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.tenant_settings.ascend import has_ascend_configured
from app.integrations.ascend.auth import login_ascend_api
from app.integrations.ascend.errors import AscendApiError
from app.tools.jwt_tokens import expires_at_from_bearer_token

if TYPE_CHECKING:
    from app.repositories.ascend_oauth_repository import AscendOAuthRepository

logger = get_logger(__name__)

_REFRESH_SKEW = timedelta(seconds=60)


def _should_refresh(expires_at: Optional[datetime]) -> bool:
    if expires_at is None:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at - _REFRESH_SKEW <= datetime.now(timezone.utc)


class AscendOAuthService:
    def __init__(self, repository: Optional[AscendOAuthRepository] = None) -> None:
        self._repo = repository

    def _repo_or(self, repos: Any) -> AscendOAuthRepository:
        from app.repositories.ascend_oauth_repository import AscendOAuthRepository

        return self._repo or AscendOAuthRepository(repos.session)

    def _get_row(self, tenant_slug: str) -> Optional[dict[str, Any]]:
        if self._repo is not None:
            return self._repo.get_row_by_tenant_slug(tenant_slug)
        return run_with_repos(
            lambda repos: self._repo_or(repos).get_row_by_tenant_slug(tenant_slug)
        )

    def has_credentials(self, tenant_slug: str) -> bool:
        slug = (tenant_slug or "").strip()
        if not slug:
            return False
        if self._repo is not None:
            cfg = self._repo.load_config_by_slug(slug)
        else:
            cfg = run_with_repos(lambda repos: self._repo_or(repos).load_config_by_slug(slug))
        if not cfg:
            return False
        return has_ascend_configured(cfg)

    def get_access_token(self, tenant_slug: str) -> str | None:
        slug = (tenant_slug or "").strip()
        if not slug:
            return None

        row = self._get_row(slug)
        if not row:
            return None

        token = str(row.get("access_token") or "").strip()
        if token and not _should_refresh(expires_at_from_bearer_token(token)):
            return token

        email = str(row.get("email") or "").strip()
        if not email:
            return None

        key = settings.TURVO_OAUTH_ENCRYPTION_KEY
        ciphertext = str(row.get("password_ciphertext") or "").strip()
        if not ciphertext:
            return None
        try:
            plain = decrypt_password(ciphertext, key)
        except ValueError as exc:
            logger.warning("Ascend password decrypt failed tenant=%s: %s", slug, exc)
            return None

        try:
            data = login_ascend_api(email=email, password=plain)
        except AscendApiError as exc:
            logger.warning("Ascend login failed tenant=%s: %s", slug, exc)
            return None

        access_token = str(data.get("accessToken") or "").strip()
        if not access_token:
            return None

        expires_at = expires_at_from_bearer_token(access_token)
        if expires_at is None:
            logger.warning("Ascend accessToken missing JWT exp tenant=%s", slug)

        ciphertext = encrypt_password(plain, key)

        def persist() -> None:
            if self._repo is not None:
                self._repo.upsert_oauth(
                    slug,
                    email=email,
                    password_ciphertext=ciphertext,
                    access_token=access_token,
                    access_token_expires_at=expires_at,
                )
            else:
                run_with_repos(
                    lambda repos: self._repo_or(repos).upsert_oauth(
                        slug,
                        email=email,
                        password_ciphertext=ciphertext,
                        access_token=access_token,
                        access_token_expires_at=expires_at,
                    )
                )

        persist()
        return access_token
