"""Tests for TurvoApiClient transient retries and exhaustion."""

from __future__ import annotations

import json
from typing import Any, Optional
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.domain.tenant_settings.tms import TmsSettings
from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError


class _FakeOAuthService:
    def __init__(self, tokens: list[dict[str, Any]] | None = None):
        self._tokens = list(tokens or [{"access_token": "tok-1"}])
        self.refresh_calls: list[str] = []

    async def get_tenant_tokens(self, tenant_slug: str, proactive_refresh: bool = True):
        if not self._tokens:
            return None
        return self._tokens[0]

    async def refresh_tenant_token(self, tenant_slug: str):
        self.refresh_calls.append(tenant_slug)
        if len(self._tokens) > 1:
            self._tokens.pop(0)
        return {"success": True}


def _fake_tms() -> TmsSettings:
    return TmsSettings(
        public_api_url="https://my-sandbox-publicapi.turvo.com",
        x_api_key="test-x-key",
    )


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


def _wire_client(monkeypatch: pytest.MonkeyPatch) -> TurvoApiClient:
    monkeypatch.setattr(TurvoApiClient, "_load_tms", lambda self, slug: _fake_tms())
    monkeypatch.setattr(settings, "TURVO_HTTP_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "TURVO_HTTP_RETRY_BASE_S", 0.0)
    monkeypatch.setattr(settings, "TURVO_HTTP_RETRY_MAX_S", 0.0)
    monkeypatch.setattr("app.integrations.turvo.public_api_client.asyncio.sleep", AsyncMock())
    return TurvoApiClient(oauth_service=_FakeOAuthService())


@pytest.mark.asyncio
async def test_500_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _wire_client(monkeypatch)
    responses = [_httpx_response(500), _httpx_response(500), _httpx_response(200, {"ok": True})]
    send_calls = 0

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        nonlocal send_calls
        send_calls += 1
        return responses.pop(0)

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    out = await client.request("t3ra", "GET", "/shipments/1")
    assert out == {"ok": True}
    assert send_calls == 3


@pytest.mark.asyncio
async def test_500_exhaustion_raises_normalized_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _wire_client(monkeypatch)

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        return _httpx_response(500)

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    with pytest.raises(TurvoApiError) as exc_info:
        await client.request("t3ra", "GET", "/shipments/1")
    assert exc_info.value.status_code is None
    assert "TMS connection timed out after 5 attempts" in str(exc_info.value)


@pytest.mark.asyncio
async def test_404_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _wire_client(monkeypatch)
    send_calls = 0

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        nonlocal send_calls
        send_calls += 1
        return _httpx_response(404, "missing")

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    with pytest.raises(TurvoApiError) as exc_info:
        await client.request("t3ra", "GET", "/shipments/missing")
    assert exc_info.value.status_code == 404
    assert send_calls == 1


@pytest.mark.asyncio
async def test_transport_error_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _wire_client(monkeypatch)

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        raise httpx.ReadTimeout("timed out")

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    with pytest.raises(TurvoApiError) as exc_info:
        await client.request("t3ra", "GET", "/shipments/1")
    assert exc_info.value.status_code is None
    assert "TMS connection timed out after 5 attempts" in str(exc_info.value)


@pytest.mark.asyncio
async def test_401_refresh_does_not_consume_transient_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    oauth = _FakeOAuthService(
        [{"access_token": "tok-1"}, {"access_token": "tok-2"}]
    )
    monkeypatch.setattr(TurvoApiClient, "_load_tms", lambda self, slug: _fake_tms())
    monkeypatch.setattr(settings, "TURVO_HTTP_MAX_ATTEMPTS", 5)
    monkeypatch.setattr(settings, "TURVO_HTTP_RETRY_BASE_S", 0.0)
    monkeypatch.setattr(settings, "TURVO_HTTP_RETRY_MAX_S", 0.0)
    monkeypatch.setattr("app.integrations.turvo.public_api_client.asyncio.sleep", AsyncMock())
    client = TurvoApiClient(oauth_service=oauth)
    responses = [_httpx_response(401), _httpx_response(200, {"id": 1})]

    async def fake_send(self, method, url, headers, params, json_body, timeout_s, *, files=None):
        return responses.pop(0)

    monkeypatch.setattr(TurvoApiClient, "_send", fake_send)
    out = await client.request("t3ra", "GET", "/shipments/1")
    assert out == {"id": 1}
    assert oauth.refresh_calls == ["t3ra"]
