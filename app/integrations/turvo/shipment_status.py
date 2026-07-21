"""Turvo App API shipment status update (updateShipmentStatusById)."""

from __future__ import annotations

import json
from typing import Any

import httpx

from app.core.config import settings
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.public_api_urls import resolve_turvo_ui_base_url
from app.integrations.turvo.webhook_mapping import TENDERED_STATUS_CODE_KEY
from app.services.turvo_oauth_service import TurvoOAuthService

TENDER_CODE_ID = 100161
TENDER_CODE_KEY = TENDERED_STATUS_CODE_KEY
TENDER_CODE_VALUE = "Tendered"
TENDER_COMPONENT_KEY = 11033

_APP_SHIPMENT_TYPES = [
    "general",
    "permissions",
    "groups",
    "commissions",
    "bids",
    "topCarriers",
    "documents",
]


def _details(payload: dict[str, Any]) -> dict[str, Any]:
    raw = payload.get("details")
    return raw if isinstance(raw, dict) else payload


def status_code_key_from_shipment_payload(payload: dict[str, Any]) -> str | None:
    details = _details(payload)
    status = details.get("status")
    if not isinstance(status, dict):
        return None
    code = status.get("code")
    if not isinstance(code, dict):
        return None
    key = code.get("key")
    return str(key).strip() if key is not None else None


def fragment_id_from_shipment_payload(payload: dict[str, Any]) -> str | None:
    """Extract status fragment_id from App or Public API shipment payload."""
    details = _details(payload)
    for route_key in ("globalRoute", "global_route"):
        route_block = details.get(route_key)
        if isinstance(route_block, dict):
            fragments = route_block.get("fragments")
            if isinstance(fragments, list) and fragments:
                first = fragments[0]
                if isinstance(first, dict):
                    fid = first.get("fragment_id") or first.get("fragmentId")
                    if fid is not None and str(fid).strip():
                        return str(fid).strip()
    fragments = details.get("fragments")
    if isinstance(fragments, list) and fragments:
        first = fragments[0]
        if isinstance(first, dict):
            fid = first.get("fragment_id") or first.get("fragmentId")
            if fid is not None and str(fid).strip():
                return str(fid).strip()
    return None


def timezone_from_shipment_payload(payload: dict[str, Any], *, default: str = "US/Pacific") -> str:
    details = _details(payload)
    for route_key in ("globalRoute", "global_route"):
        route = details.get(route_key)
        if not isinstance(route, list):
            continue
        for stop in reversed(route):
            if not isinstance(stop, dict):
                continue
            appt = stop.get("appointment")
            if isinstance(appt, dict):
                tz = appt.get("timeZone") or appt.get("timezone")
                if tz is not None and str(tz).strip():
                    return str(tz).strip()
            tz = stop.get("timezone")
            if tz is not None and str(tz).strip():
                return str(tz).strip()
    return default


def build_tender_status_body(*, fragment_id: str, timezone: str) -> dict[str, Any]:
    return {
        "timezone": timezone,
        "tags": [],
        "fragment_id": fragment_id,
        "notes": "",
        "description": TENDER_CODE_VALUE,
        "code": {
            "id": TENDER_CODE_ID,
            "key": TENDER_CODE_KEY,
            "value": TENDER_CODE_VALUE,
        },
        "sharing": {"notes": {"entities": []}},
        "use_routing_guide": True,
        "reason": {},
        "componentKey": TENDER_COMPONENT_KEY,
    }


async def _auth_headers(
    oauth: TurvoOAuthService,
    tenant_slug: str,
) -> tuple[dict[str, str], Any]:
    tms = oauth._load_tms(tenant_slug)
    tokens = await oauth.get_tenant_tokens(tenant_slug)
    access = (tokens or {}).get("access_token")
    if not access:
        raise TurvoApiError(
            "Turvo account not linked or no access token available",
            status_code=401,
        )
    headers = {
        "Authorization": f"Bearer {access}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    x_key = (tms.x_api_key or settings.TURVO_X_API_KEY or "").strip()
    if x_key:
        headers["x-api-key"] = x_key
    return headers, tms


def _resolve_ui_base(tms: Any, tenant_slug: str) -> str:
    ui_base = resolve_turvo_ui_base_url(
        ui_base_url=tms.ui_base_url,
        public_api_url=tms.public_api_url or "",
    )
    if not ui_base:
        raise TurvoApiError(
            f"Tenant {tenant_slug!r} TMS: set tms.ui_base_url or a derivable tms.public_api_url",
            status_code=503,
        )
    return ui_base


async def fetch_app_shipment_details(
    tenant_slug: str,
    shipment_id: str,
    *,
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    """GET App API shipment (includes global_route.fragments for status PUT)."""
    sid = str(shipment_id or "").strip()
    slug = str(tenant_slug or "").strip()
    if not sid:
        raise ValueError("shipment_id is required")
    if not slug:
        raise ValueError("tenant_slug is required")

    oauth_svc = oauth or TurvoOAuthService()
    headers, tms = await _auth_headers(oauth_svc, slug)
    ui_base = _resolve_ui_base(tms, slug)

    params = {
        "types": json.dumps(_APP_SHIPMENT_TYPES, separators=(",", ":")),
        "event": "join",
    }
    url = f"{ui_base.rstrip('/')}/api/shipments/{sid}"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.get(url, headers=headers, params=params)

    if resp.status_code in (401, 403):
        await oauth_svc.refresh_tenant_token(slug)
        headers, _tms = await _auth_headers(oauth_svc, slug)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(url, headers=headers, params=params)

    if resp.status_code != 200:
        raise TurvoApiError(
            f"App API GET shipment returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:2000] if resp.text else None,
        )

    data = resp.json()
    if not isinstance(data, dict):
        raise TurvoApiError("App API shipment response was not a JSON object")
    return data


async def update_shipment_tender_status(
    tenant_slug: str,
    shipment_id: str,
    body: dict[str, Any],
    *,
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    """PUT App API updateShipmentStatusById (Tendered / 2101)."""
    sid = str(shipment_id or "").strip()
    slug = str(tenant_slug or "").strip()
    if not sid:
        raise ValueError("shipment_id is required")
    if not slug:
        raise ValueError("tenant_slug is required")

    oauth_svc = oauth or TurvoOAuthService()
    headers, tms = await _auth_headers(oauth_svc, slug)
    ui_base = _resolve_ui_base(tms, slug)
    url = f"{ui_base.rstrip('/')}/api/shipments/status/{sid}?fullResponse=true"

    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.put(url, headers=headers, json=body)

    if resp.status_code in (401, 403):
        await oauth_svc.refresh_tenant_token(slug)
        headers, _tms = await _auth_headers(oauth_svc, slug)
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.put(url, headers=headers, json=body)

    if resp.status_code not in (200, 201):
        raise TurvoApiError(
            f"App API status PUT returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:2000] if resp.text else None,
        )

    data = resp.json()
    return data if isinstance(data, dict) else {"raw": data}


__all__ = (
    "TENDER_CODE_ID",
    "TENDER_CODE_KEY",
    "TENDER_CODE_VALUE",
    "TENDER_COMPONENT_KEY",
    "build_tender_status_body",
    "fetch_app_shipment_details",
    "fragment_id_from_shipment_payload",
    "status_code_key_from_shipment_payload",
    "timezone_from_shipment_payload",
    "update_shipment_tender_status",
)
