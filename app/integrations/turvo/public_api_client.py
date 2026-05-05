"""Outbound HTTP client for Turvo's Public API v1 (not FreightX ``app.api``).

This module issues **outbound** requests **to Turvo**. ``app.api`` is **inbound**
HTTP for this service; keep that distinction when navigating the codebase.

Integration-layer I/O only (not a generic TMS abstraction). Graphs and agents
should call ``app.tools.turvo`` for sync workflow entrypoints; those tools
delegate here for HTTP.

``TurvoApiClient`` centralizes bearer token resolution via ``TurvoOAuthService``,
required headers (e.g. ``x-api-key``), 401/403 refresh + single retry, and JSON
parsing. Other modules under ``app.integrations.turvo`` use this client and
must not build ``Authorization`` headers themselves.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.public_api_urls import (
    build_publicapi_v1_url,
    normalize_turvo_publicapi_url,
)
from app.services.turvo_oauth_service import TurvoOAuthService

logger = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 60.0
_MAX_ATTEMPTS = 2


class TurvoApiError(Exception):
    """Raised when Turvo Public API returns a non-2xx response or response is unusable."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class TurvoApiClient:
    """HTTP client for outbound calls to Turvo Public API v1."""

    def __init__(self, oauth_service: Optional[TurvoOAuthService] = None):
        self._oauth = oauth_service or TurvoOAuthService()

    async def _resolve_token(self, app_user_id: str) -> str:
        tokens = await self._oauth.get_user_tokens(app_user_id)
        if not tokens or not tokens.get("access_token"):
            raise TurvoApiError(
                "Turvo account not linked or no access token available",
                status_code=401,
            )
        return tokens["access_token"]

    def _build_headers(self, access_token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if settings.TURVO_X_API_KEY:
            headers["x-api-key"] = settings.TURVO_X_API_KEY
        return headers

    def _build_url(self, path: str) -> str:
        if not settings.TURVO_PUBLICAPI_URL:
            raise TurvoApiError("TURVO_PUBLICAPI_URL is not configured")
        base = normalize_turvo_publicapi_url(settings.TURVO_PUBLICAPI_URL)
        return build_publicapi_v1_url(base, path)

    async def _send(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: Optional[dict[str, Any]],
        json_body: Optional[dict[str, Any]],
        timeout_s: float,
    ) -> httpx.Response:
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                if json_body is not None:
                    return await client.request(
                        method, url, headers=headers, params=params, json=json_body
                    )
                return await client.request(method, url, headers=headers, params=params)
        except httpx.HTTPError as e:
            raise TurvoApiError(f"Turvo HTTP error: {e}") from e

    def _parse_success(self, resp: httpx.Response) -> dict[str, Any]:
        try:
            return resp.json()
        except Exception as e:
            raise TurvoApiError(
                "Turvo response was not valid JSON",
                status_code=resp.status_code,
                body=resp.text,
            ) from e

    def _raise_for_status(self, method: str, path: str, resp: httpx.Response) -> None:
        raise TurvoApiError(
            f"Turvo {method} {path} returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:1000] if resp.text else None,
        )

    async def request(
        self,
        app_user_id: str,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        url = self._build_url(path)
        access_token = await self._resolve_token(app_user_id)

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            headers = self._build_headers(access_token)
            resp = await self._send(method, url, headers, params, json_body, timeout_s)

            if resp.status_code in (401, 403) and attempt < _MAX_ATTEMPTS:
                logger.info(
                    "Turvo %s %s returned %s; refreshing token and retrying",
                    method,
                    path,
                    resp.status_code,
                )
                try:
                    await self._oauth.refresh_user_token(app_user_id)
                except Exception as e:
                    raise TurvoApiError(
                        f"Token refresh failed after {resp.status_code}: {e}",
                        status_code=resp.status_code,
                    ) from e
                access_token = await self._resolve_token(app_user_id)
                continue

            if 200 <= resp.status_code < 300:
                return self._parse_success(resp)

            self._raise_for_status(method, path, resp)

        raise TurvoApiError(f"Turvo {method} {path} failed after {_MAX_ATTEMPTS} attempts")
