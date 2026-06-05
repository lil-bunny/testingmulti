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

from app.core.logger import get_logger
from app.domain.tenant_settings.tms import TmsSettings
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

    def __init__(
        self,
        oauth_service: Optional[TurvoOAuthService] = None,
    ):
        self._oauth = oauth_service or TurvoOAuthService()

    def _load_tms(self, tenant_slug: str) -> TmsSettings:
        return self._oauth._load_tms(tenant_slug)

    async def _resolve_token(self, tenant_slug: str) -> str:
        tokens = await self._oauth.get_tenant_tokens(tenant_slug)
        if not tokens or not tokens.get("access_token"):
            raise TurvoApiError(
                "Turvo account not linked or no access token available",
                status_code=401,
            )
        return tokens["access_token"]

    def _build_headers(self, tms: TmsSettings, access_token: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        x_key = (tms.x_api_key or "").strip()
        if x_key:
            headers["x-api-key"] = x_key
        return headers

    def _build_url(self, tms: TmsSettings, path: str) -> str:
        public_api_url = (tms.public_api_url or "").strip()
        if not public_api_url:
            raise TurvoApiError(
                f"Tenant TMS public_api_url is not configured",
                status_code=503,
            )
        base = normalize_turvo_publicapi_url(public_api_url)
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
        tenant_slug: str,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> dict[str, Any]:
        slug = (tenant_slug or "").strip()
        if not slug:
            raise TurvoApiError("tenant_slug is required for Turvo API calls", status_code=401)

        tms = self._load_tms(slug)
        url = self._build_url(tms, path)
        access_token = await self._resolve_token(slug)

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            headers = self._build_headers(tms, access_token)
            resp = await self._send(method, url, headers, params, json_body, timeout_s)

            if resp.status_code in (401, 403) and attempt < _MAX_ATTEMPTS:
                logger.info(
                    "Turvo %s %s returned %s; refreshing token and retrying",
                    method,
                    path,
                    resp.status_code,
                )
                try:
                    await self._oauth.refresh_tenant_token(slug)
                except Exception as e:
                    raise TurvoApiError(
                        f"Token refresh failed after {resp.status_code}: {e}",
                        status_code=resp.status_code,
                    ) from e
                access_token = await self._resolve_token(slug)
                continue

            if 200 <= resp.status_code < 300:
                return self._parse_success(resp)

            self._raise_for_status(method, path, resp)

        raise TurvoApiError(f"Turvo {method} {path} failed after {_MAX_ATTEMPTS} attempts")
