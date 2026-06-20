"""Turvo web UI accounts API (outbound) — phone search via shipment driver history."""

from __future__ import annotations

import json
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.integrations.turvo.contacts import get_driver_contact
from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError
from app.integrations.turvo.public_api_urls import build_turvo_ui_base_url
from app.services.turvo_oauth_service import TurvoOAuthService
from app.tools.driver_details import names_match, phones_match

# ponytail: large response (~500KB); dedicated phone endpoint would be better if Turvo adds one
_UI_ACCOUNT_TYPES = ["general", "permissions"]


def driver_rows_from_shipments(
    payload: dict[str, Any], *, carrier_id: int
) -> list[dict[str, Any]]:
    """Extract driver name/phone/id from UI accounts shipments embed."""
    cid = str(carrier_id)
    rows: list[dict[str, Any]] = []
    for shipment in (payload.get("shipments") or {}).get("shipments") or []:
        if not isinstance(shipment, dict):
            continue
        details = shipment.get("details") if isinstance(shipment.get("details"), dict) else {}
        for order in details.get("carrier_orders") or []:
            if not isinstance(order, dict):
                continue
            carrier = order.get("carrier") if isinstance(order.get("carrier"), dict) else {}
            if str(carrier.get("id") or "") != cid:
                continue
            for driver in order.get("drivers") or []:
                if not isinstance(driver, dict):
                    continue
                ctx = driver.get("context") if isinstance(driver.get("context"), dict) else {}
                phone_obj = driver.get("phone") if isinstance(driver.get("phone"), dict) else {}
                number = phone_obj.get("number")
                contact_id = ctx.get("id")
                if contact_id is None:
                    continue
                rows.append(
                    {
                        "contact_id": int(contact_id),
                        "name": ctx.get("name"),
                        "phone": str(number) if number else None,
                    }
                )
    return rows


def filter_driver_rows_by_phone(
    rows: list[dict[str, Any]],
    *,
    phone: str,
    name: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        row_phone = row.get("phone")
        if not row_phone or not phones_match(phone, str(row_phone)):
            continue
        if name and str(name).strip() and not names_match(name, row.get("name")):
            continue
        out.append(row)
    return out


async def _fetch_ui_account(
    tenant_slug: str,
    account_id: int,
    *,
    types: list[str],
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    oauth_svc = oauth or TurvoOAuthService()
    tms = oauth_svc._load_tms(tenant_slug)
    ui_base = build_turvo_ui_base_url(tms.public_api_url or "")
    if not ui_base:
        raise TurvoApiError(
            f"Tenant {tenant_slug!r} TMS public_api_url cannot derive UI base URL",
            status_code=503,
        )
    token = await oauth_svc.get_tenant_tokens(tenant_slug)
    access = (token or {}).get("access_token")
    if not access:
        raise TurvoApiError(
            "Turvo account not linked or no access token available",
            status_code=401,
        )
    params = urlencode({"card": "details", "types": json.dumps(types)})
    url = f"{ui_base.rstrip('/')}/api/accounts/{account_id}?{params}"
    headers = {
        "authorization": f"Bearer {access}",
        "accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.HTTPError as e:
        raise TurvoApiError(f"Turvo UI HTTP error: {e}") from e
    if resp.status_code != 200:
        raise TurvoApiError(
            f"Turvo UI GET /api/accounts/{account_id} returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text[:1000] if resp.text else None,
        )
    data = resp.json()
    if not isinstance(data, dict):
        raise TurvoApiError("Turvo UI response was not a JSON object")
    return data


async def search_carrier_driver_contacts_by_phone(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    phone: str,
    name: str | None = None,
    client: Optional[TurvoApiClient] = None,
    oauth: TurvoOAuthService | None = None,
) -> list[dict[str, Any]]:
    """Search carrier drivers by phone via Turvo UI accounts API (shipments embed).

    Carrier account id equals carrier_id in sandbox/production carrier records.
    """
    _ = carrier_name  # reserved for future UI filters; carrier_id scopes shipment rows
    payload = await _fetch_ui_account(
        tenant_slug,
        carrier_id,
        types=_UI_ACCOUNT_TYPES,
        oauth=oauth,
    )
    rows = driver_rows_from_shipments(payload, carrier_id=carrier_id)
    matched = filter_driver_rows_by_phone(rows, phone=phone, name=name)
    seen: set[int] = set()
    contact_ids: list[int] = []
    for row in matched:
        cid = row.get("contact_id")
        if cid is None:
            continue
        try:
            key = int(cid)
        except (TypeError, ValueError):
            continue
        if key in seen:
            continue
        seen.add(key)
        contact_ids.append(key)

    api = client or TurvoApiClient()
    out: list[dict[str, Any]] = []
    for contact_id in contact_ids:
        hydrated = await get_driver_contact(tenant_slug, contact_id, client=api)
        if hydrated is not None:
            out.append(hydrated)
    return out
