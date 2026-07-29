"""Tests for AscendOAuthService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt

from app.domain.tenant_settings.ascend import has_ascend_configured
from app.services.ascend_oauth_service import AscendOAuthService


def _jwt(*, exp_offset_seconds: int) -> str:
    exp = int(
        (datetime.now(timezone.utc) + timedelta(seconds=exp_offset_seconds)).timestamp()
    )
    return jwt.encode({"exp": exp}, "secret", algorithm="HS256")


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


def test_get_access_token_reuses_cached_jwt() -> None:
    cached = _jwt(exp_offset_seconds=7200)
    repo = MagicMock()
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": cached,
    }
    svc = AscendOAuthService(repository=repo)

    with patch("app.services.ascend_oauth_service.login_ascend_api") as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == cached
    login_mock.assert_not_called()


def test_get_access_token_logs_in_when_missing() -> None:
    fresh = _jwt(exp_offset_seconds=3600)
    repo = MagicMock()
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": None,
    }
    svc = AscendOAuthService(repository=repo)

    with patch(
        "app.services.ascend_oauth_service.login_ascend_api",
        return_value={"accessToken": fresh},
    ) as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == fresh
    login_mock.assert_called_once_with(email="a@example.com", password="secret")
    repo.upsert_oauth.assert_called_once()
    expires_at = repo.upsert_oauth.call_args.kwargs["access_token_expires_at"]
    assert expires_at is not None
    assert expires_at > datetime.now(timezone.utc)


def test_get_access_token_relogins_when_jwt_expired() -> None:
    expired = _jwt(exp_offset_seconds=-120)
    fresh = _jwt(exp_offset_seconds=3600)
    repo = MagicMock()
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": expired,
    }
    svc = AscendOAuthService(repository=repo)

    with patch(
        "app.services.ascend_oauth_service.login_ascend_api",
        return_value={"accessToken": fresh},
    ) as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == fresh
    login_mock.assert_called_once()


def test_get_access_token_relogins_when_cached_token_not_jwt() -> None:
    fresh = _jwt(exp_offset_seconds=3600)
    repo = MagicMock()
    repo.get_row_by_tenant_slug.return_value = {
        "tenant_slug": "t3ra",
        "email": "a@example.com",
        "password_ciphertext": "plain:secret",
        "access_token": "cached-token",
    }
    svc = AscendOAuthService(repository=repo)

    with patch(
        "app.services.ascend_oauth_service.login_ascend_api",
        return_value={"accessToken": fresh},
    ) as login_mock:
        token = svc.get_access_token("t3ra")

    assert token == fresh
    login_mock.assert_called_once()
