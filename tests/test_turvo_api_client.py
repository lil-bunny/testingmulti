"""Unit tests for outbound Turvo Public API HTTP client (token, 401 refresh+retry, errors)."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx
import pytest

from app.integrations.turvo import public_api_client as turvo_public_api_module
from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError


class _FakeOAuthService:
    def __init__(self, tokens_sequence: list[Optional[dict[str, Any]]]):
        self._sequence = list(tokens_sequence)
        self.refresh_calls: list[str] = []

    async def get_user_tokens(self, app_user_id: str):
        if not self._sequence:
            return None
        return self._sequence.pop(0)

    async def refresh_user_token(self, app_user_id: str):
        self.refresh_calls.append(app_user_id)
        return {"success": True}


def _patch_settings(monkeypatch, base_url: str = "https://my-sandbox-publicapi.turvo.com", x_api_key: Optional[str] = "test-x-key"):
    monkeypatch.setattr(turvo_public_api_module.settings, "TURVO_PUBLICAPI_URL", base_url, raising=False)
    monkeypatch.setattr(turvo_public_api_module.settings, "TURVO_X_API_KEY", x_api_key, raising=False)


def _httpx_response(status_code: int, body: dict | str | None = None) -> httpx.Response:
    if isinstance(body, dict):
        content = json.dumps(body).encode("utf-8")
        headers = {"content-type": "application/json"}
    elif isinstance(body, str):
        content = body.encode("utf-8")
        headers = {"content-type": "text/plain"}
    else:
        content = b""
        headers = {}
    return httpx.Response(status_code=status_code, content=content, headers=headers)


@pytest.mark.asyncio
async def test_request_returns_json_on_200(monkeypatch):
    _patch_settings(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_send(self, method, url, headers, params, json_body, timeout_s):
        captured["method"] = method
        captured["url"] = url
        captured["headers"] = headers
        return _httpx_response(200, {"id": 1, "ok": True})

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    client = TurvoApiClient(oauth_service=_FakeOAuthService([{"access_token": "tok-1"}]))
    out = await client.request(app_user_id="user-1", method="GET", path="/shipments/1")

    assert out == {"id": 1, "ok": True}
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/v1/shipments/1")
    assert captured["headers"]["Authorization"] == "Bearer tok-1"
    assert captured["headers"]["x-api-key"] == "test-x-key"


@pytest.mark.asyncio
async def test_request_refreshes_and_retries_on_401(monkeypatch):
    _patch_settings(monkeypatch)
    responses = [
        _httpx_response(401, "unauthorized"),
        _httpx_response(200, {"id": 1}),
    ]
    seen_auth_headers: list[str] = []

    async def fake_send(self, method, url, headers, params, json_body, timeout_s):
        seen_auth_headers.append(headers["Authorization"])
        return responses.pop(0)

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    oauth = _FakeOAuthService(
        [{"access_token": "tok-1"}, {"access_token": "tok-2"}]
    )
    client = TurvoApiClient(oauth_service=oauth)

    out = await client.request(app_user_id="user-1", method="GET", path="/shipments/1")

    assert out == {"id": 1}
    assert oauth.refresh_calls == ["user-1"]
    assert seen_auth_headers == ["Bearer tok-1", "Bearer tok-2"]


@pytest.mark.asyncio
async def test_request_raises_when_token_missing(monkeypatch):
    _patch_settings(monkeypatch)
    client = TurvoApiClient(oauth_service=_FakeOAuthService([None]))
    with pytest.raises(TurvoApiError) as ei:
        await client.request(app_user_id="user-1", method="GET", path="/shipments/1")
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_request_raises_on_non_2xx(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_send(self, method, url, headers, params, json_body, timeout_s):
        return _httpx_response(500, "boom")

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    client = TurvoApiClient(oauth_service=_FakeOAuthService([{"access_token": "tok-1"}]))
    with pytest.raises(TurvoApiError) as ei:
        await client.request(app_user_id="user-1", method="GET", path="/shipments/1")
    assert ei.value.status_code == 500
    assert "boom" in (ei.value.body or "")


@pytest.mark.asyncio
async def test_request_raises_when_publicapi_url_missing(monkeypatch):
    _patch_settings(monkeypatch, base_url=None)
    client = TurvoApiClient(oauth_service=_FakeOAuthService([{"access_token": "tok-1"}]))
    with pytest.raises(TurvoApiError):
        await client.request(app_user_id="user-1", method="GET", path="/shipments/1")
