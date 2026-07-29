"""Turvo UI activity list API (internal app URL, not Public API v1)."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import httpx

from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.public_api_urls import resolve_turvo_ui_base_url
from app.services.turvo_oauth_service import TurvoOAuthService

_ACTIVITY_FILTER = {
    "pageSize": 24,
    "start": 0,
    "criteria": [
        {
            "key": "context_snapshot.snapshot_attributes.type.id",
            "function": "nin",
            "values": [13327555],
        }
    ],
}


async def fetch_shipment_activity_list(
    tenant_slug: str,
    shipment_id: str,
    *,
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    """GET ``/api/activity/list`` for a shipment context."""
    sid = str(shipment_id or "").strip()
    slug = str(tenant_slug or "").strip()
    if not sid:
        raise ValueError("shipment_id is required")
    if not slug:
        raise ValueError("tenant_slug is required")

    oauth_svc = oauth or TurvoOAuthService()
    tms = oauth_svc._load_tms(slug)
    ui_base = resolve_turvo_ui_base_url(
        ui_base_url=tms.ui_base_url,
        public_api_url=tms.public_api_url or "",
    )
    if not ui_base:
        raise TurvoApiError(
            f"Tenant {slug!r} TMS: set tms.ui_base_url or a derivable tms.public_api_url",
            status_code=503,
        )

    token = await oauth_svc.get_tenant_tokens(slug)
    access = (token or {}).get("access_token")
    if not access:
        raise TurvoApiError(
            "Turvo account not linked or no access token available",
            status_code=401,
        )

    context_id: int | str = int(sid) if sid.isdigit() else sid
    params = {
        "filter": json.dumps(_ACTIVITY_FILTER, separators=(",", ":")),
        "context": json.dumps({"id": context_id, "type": "SHIPMENT"}, separators=(",", ":")),
    }
    url = f"{ui_base.rstrip('/')}/api/activity/list?{urlencode(params)}"
    headers = {
        "authorization": f"Bearer {access}",
        "accept": "application/json",
    }
    x_key = (tms.x_api_key or "").strip()
    if x_key:
        headers["x-api-key"] = x_key

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        raise TurvoApiError(f"Turvo activity list HTTP error: {exc}") from exc

    if resp.status_code in (401, 403):
        await oauth_svc.refresh_tenant_token(slug)
        token = await oauth_svc.get_tenant_tokens(slug, proactive_refresh=False)
        access = (token or {}).get("access_token")
        if not access:
            raise TurvoApiError(
                "Turvo account not linked or no access token available",
                status_code=401,
            )
        headers["authorization"] = f"Bearer {access}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as exc:
            raise TurvoApiError(f"Turvo activity list HTTP error: {exc}") from exc

    if resp.status_code != 200:
        raise TurvoApiError(
            f"Turvo activity list returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:1000] if resp.text else None,
        )

    data = resp.json()
    if not isinstance(data, dict):
        raise TurvoApiError("Turvo activity list response was not a JSON object")
    return data
