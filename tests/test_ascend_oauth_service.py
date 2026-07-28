"""Tests for AscendOAuthService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.domain.tenant_settings.ascend import has_ascend_configured
from app.services.ascend_oauth_service import AscendOAuthService


def test_has_ascend_configured_from_settings_ascend_block() -> None:
    cfg = {
        "ascend": {
            "email": "a@example.com",
            "password_ciphertext": "plain:secret",
        }
    }
    assert has_ascend_configured(cfg) is True


def test_has_ascend_configured_false_without_ascend_block() -> None:
    assert has_ascend_configured({}) is False
    assert has_ascend_configured({"ascend": {}}) is False
    assert has_ascend_configured({"ascend": {"email": "a@example.com"}}) is False


def test_get_access_token_reuses_cached_token() -> None:
    repo = MagicMock()
    expires = datetime.now(timezone.utc) + timedelta(hours=2)
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": "cached-token",
        "access_token_expires_at": expires,
    }
    svc = AscendOAuthService(repository=repo)

    with patch("app.services.ascend_oauth_service.login_ascend_api") as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == "cached-token"
    login_mock.assert_not_called()


def test_get_access_token_logs_in_when_missing() -> None:
    repo = MagicMock()
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": None,
        "access_token_expires_at": None,
    }
    svc = AscendOAuthService(repository=repo)

    with patch(
        "app.services.ascend_oauth_service.login_ascend_api",
        return_value={"accessToken": "fresh-token", "expiresIn": 3600},
    ) as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == "fresh-token"
    login_mock.assert_called_once_with(email="a@example.com", password="secret")
    repo.upsert_oauth.assert_called_once()
