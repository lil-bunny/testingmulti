"""Tests for freightx-api auth_client.validate_token."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.domain.auth_errors import AuthServiceUnavailableError, AuthUnauthorizedError
from app.integrations.freightx_api.auth_client import validate_token

_ME_BODY = {
    "id": "11111111-1111-1111-1111-111111111111",
    "name": "Test User",
    "email": "test@example.com",
    "tenantId": "22222222-2222-2222-2222-222222222222",
    "tenantIds": ["22222222-2222-2222-2222-222222222222"],
    "permissions": [],
}


def _mock_client(*, get_response: httpx.Response | Exception) -> MagicMock:
    client = MagicMock()
    if isinstance(get_response, Exception):
        client.get = AsyncMock(side_effect=get_response)
    else:
        client.get = AsyncMock(return_value=get_response)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_validate_token_returns_api_user():
    response = httpx.Response(200, json=_ME_BODY)
    with patch(
        "app.integrations.freightx_api.auth_client.httpx.AsyncClient",
        return_value=_mock_client(get_response=response),
    ):
        user = await validate_token("good-token")

    assert user.id == _ME_BODY["id"]
    assert user.email == _ME_BODY["email"]
    assert user.tenant_id == _ME_BODY["tenantId"]


@pytest.mark.asyncio
async def test_validate_token_401_raises_unauthorized():
    with patch(
        "app.integrations.freightx_api.auth_client.httpx.AsyncClient",
        return_value=_mock_client(get_response=httpx.Response(401)),
    ):
        with pytest.raises(AuthUnauthorizedError):
            await validate_token("bad-token")


@pytest.mark.asyncio
async def test_validate_token_503_raises_service_unavailable():
    with patch(
        "app.integrations.freightx_api.auth_client.httpx.AsyncClient",
        return_value=_mock_client(get_response=httpx.Response(503)),
    ):
        with pytest.raises(AuthServiceUnavailableError):
            await validate_token("good-token")


@pytest.mark.asyncio
async def test_validate_token_network_error_raises_service_unavailable():
    with patch(
        "app.integrations.freightx_api.auth_client.httpx.AsyncClient",
        return_value=_mock_client(
            get_response=httpx.ConnectError("connection refused"),
        ),
    ):
        with pytest.raises(AuthServiceUnavailableError):
            await validate_token("good-token")
