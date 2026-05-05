"""Turvo OAuth service behavior with mocked HTTP (no real Turvo / DB)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from unittest.mock import patch

import pytest

from app.integrations.turvo.oauth_http import TurvoOAuthHttpError
from app.services.turvo_oauth_service import TurvoOAuthService


class FakeRepo:
    def __init__(self, initial: Optional[dict[str, Any]] = None):
        self.row = initial
        self.update_calls: list[tuple[Any, ...]] = []

    def get_row(self, app_user_id: str) -> Optional[dict[str, Any]]:
        return self.row

    def upsert_user_oauth(self, *args: Any) -> None:
        pass

    def update_tokens_only(self, *args: Any) -> None:
        self.update_calls.append(args)

    def has_user(self, app_user_id: str) -> bool:
        return self.row is not None


@pytest.fixture
def fernet_key() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("ascii")


@pytest.fixture
def patch_settings(fernet_key: str, monkeypatch: pytest.MonkeyPatch):
    mock = type(
        "MS",
        (),
        {
            "TURVO_PUBLICAPI_URL": "https://sandbox.example.com",
            "TURVO_PUBLICAPI_CLIENT_ID": "appcid",
            "TURVO_PUBLICAPI_CLIENT_SECRET": "appsec",
            "TURVO_X_API_KEY": "xkey",
            "TURVO_OAUTH_ENCRYPTION_KEY": fernet_key,
        },
    )()
    monkeypatch.setattr(
        "app.services.turvo_oauth_service.settings",
        mock,
        raising=False,
    )
    return mock


@pytest.mark.asyncio
async def test_refresh_falls_back_to_password_grant(
    patch_settings: Any, fernet_key: str
):
    from app.core.at_rest_secret import encrypt_password

    ciphertext = encrypt_password("pw", fernet_key)
    repo = FakeRepo(
        {
            "app_user_id": "u1",
            "turvo_username": "tu",
            "turvo_password_ciphertext": ciphertext,
            "access_token": "old",
            "refresh_token": "bad_refresh",
            "token_type": "Bearer",
            "access_token_expires_at": None,
        }
    )
    service = TurvoOAuthService(repository=repo)

    async def fake_post(url: str, body: dict, x_key: Optional[str]) -> dict[str, Any]:
        if body.get("grant_type") == "refresh_token":
            raise TurvoOAuthHttpError("refresh failed", status_code=401)
        assert body["grant_type"] == "password"
        return {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
            "token_type": "Bearer",
        }

    with patch(
        "app.services.turvo_oauth_service.post_token",
        new=fake_post,
    ):
        out = await service.refresh_user_token("u1")

    assert out["success"] is True
    assert len(repo.update_calls) == 1
    args = repo.update_calls[0]
    assert args[1] == "new_access"
    assert args[2] == "new_refresh"


@pytest.mark.asyncio
async def test_password_grant_authenticate_persists(patch_settings: Any, fernet_key: str):
    repo = FakeRepo(None)
    repo.last_upsert: Optional[tuple[Any, ...]] = None

    def capture_upsert(*args: Any) -> None:
        repo.last_upsert = args

    repo.upsert_user_oauth = capture_upsert  # type: ignore[method-assign]
    service = TurvoOAuthService(repository=repo)

    async def mock_post(url: str, body: dict, x_key: Optional[str]) -> dict[str, Any]:
        return {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 7200,
            "token_type": "Bearer",
        }

    with patch("app.services.turvo_oauth_service.post_token", new=mock_post):
        out = await service.authenticate_user("u2", "uname", "pwsecret")

    assert out["expires_in"] == 7200
    assert out["token_type"] == "Bearer"
    assert repo.last_upsert is not None
    assert repo.last_upsert[0] == "u2"
    assert repo.last_upsert[1] == "uname"
    assert repo.last_upsert[3] == "at"
    assert repo.last_upsert[4] == "rt"


@pytest.mark.asyncio
async def test_get_user_tokens_triggers_refresh_when_expired(
    patch_settings: Any, fernet_key: str
):
    from app.core.at_rest_secret import encrypt_password

    ciphertext = encrypt_password("pw", fernet_key)
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    repo = FakeRepo(
        {
            "app_user_id": "u3",
            "turvo_username": "tu",
            "turvo_password_ciphertext": ciphertext,
            "access_token": "expired",
            "refresh_token": "r1",
            "token_type": "Bearer",
            "access_token_expires_at": past,
        }
    )
    service = TurvoOAuthService(repository=repo)

    refresh_done = {"n": 0}

    async def fake_refresh(self: TurvoOAuthService, uid: str) -> dict[str, Any]:
        refresh_done["n"] += 1
        repo.row = {
            **repo.row,
            "access_token": "fresh",
            "access_token_expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        }
        return {"success": True}

    with patch.object(TurvoOAuthService, "refresh_user_token", new=fake_refresh):
        tokens = await service.get_user_tokens("u3", proactive_refresh=True)

    assert refresh_done["n"] == 1
    assert tokens and tokens["access_token"] == "fresh"
