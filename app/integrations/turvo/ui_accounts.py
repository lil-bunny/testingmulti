"""Turvo web UI accounts API (outbound) — carrier driver search via contacts tab."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.integrations.turvo.contacts import get_driver_contact
from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError
from app.integrations.turvo.public_api_urls import resolve_turvo_ui_base_url
from app.services.turvo_oauth_service import TurvoOAuthService
from app.tools.driver_details import name_tokens_match, names_match, phones_match

_DRIVER_ROLE_KEY = "1993"
_UI_CONTACTS_PAGE_SIZE = 200
# ponytail: caps carrier directory scan; raise if tenants exceed ~2000 driver contacts
_UI_CONTACTS_MAX_PAGES = 10


def _row_phone_numbers(row: dict[str, Any]) -> list[str]:
    numbers: list[str] = []
    single = row.get("phone")
    if single:
        numbers.append(str(single))
    for p in row.get("phones") or []:
        if p:
            numbers.append(str(p))
    return numbers


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


def _is_ui_driver_role(roles: Any) -> bool:
    if not isinstance(roles, list):
        return False
    for role in roles:
        if not isinstance(role, dict):
            continue
        if str(role.get("key") or "") == _DRIVER_ROLE_KEY:
            return True
        if str(role.get("value") or "").strip().lower() == "driver":
            return True
    return False


def driver_rows_from_contacts_tab(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract driver contacts from UI accounts contacts tab embed."""
    rows: list[dict[str, Any]] = []
    data = (payload.get("contacts") or {}).get("data") or []
    if not isinstance(data, list):
        return rows
    for item in data:
        if not isinstance(item, dict):
            continue
        basic = item.get("Basic")
        if not isinstance(basic, dict):
            continue
        if not _is_ui_driver_role(basic.get("roles")):
            continue
        contact_id = basic.get("contactId")
        if contact_id is None:
            continue
        phones = [
            str(p.get("number"))
            for p in (basic.get("phones") or [])
            if isinstance(p, dict) and p.get("number")
        ]
        rows.append(
            {
                "contact_id": int(contact_id),
                "name": basic.get("full_name") or basic.get("name"),
                "phones": phones,
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
        if not any(phones_match(phone, p) for p in _row_phone_numbers(row)):
            continue
        if name and str(name).strip() and not names_match(name, row.get("name")):
            continue
        out.append(row)
    return out


def filter_driver_rows_by_name(
    rows: list[dict[str, Any]],
    *,
    name: str,
) -> list[dict[str, Any]]:
    cleaned = str(name or "").strip()
    if not cleaned:
        return []
    return [row for row in rows if name_tokens_match(cleaned, row.get("name"))]


async def _fetch_ui_accounts(
    tenant_slug: str,
    account_id: int,
    *,
    params: dict[str, str],
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    oauth_svc = oauth or TurvoOAuthService()
    tms = oauth_svc._load_tms(tenant_slug)
    ui_base = resolve_turvo_ui_base_url(
        ui_base_url=tms.ui_base_url,
        public_api_url=tms.public_api_url or "",
    )
    if not ui_base:
        raise TurvoApiError(
            f"Tenant {tenant_slug!r} TMS: set tms.ui_base_url or a derivable tms.public_api_url",
            status_code=503,
        )
    token = await oauth_svc.get_tenant_tokens(tenant_slug)
    access = (token or {}).get("access_token")
    if not access:
        raise TurvoApiError(
            "Turvo account not linked or no access token available",
            status_code=401,
        )
    url = f"{ui_base.rstrip('/')}/api/accounts/{account_id}?{urlencode(params)}"
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


async def _fetch_ui_contacts_tab(
    tenant_slug: str,
    account_id: int,
    *,
    start: int = 0,
    page_size: int = _UI_CONTACTS_PAGE_SIZE,
    oauth: TurvoOAuthService | None = None,
) -> dict[str, Any]:
    filter_body = json.dumps(
        {"contacts": {"start": start, "pageSize": page_size}, "criteria": []},
        separators=(",", ":"),
    )
    params = {
        "types": json.dumps(["contacts"]),
        "filter": filter_body,
    }
    return await _fetch_ui_accounts(
        tenant_slug, account_id, params=params, oauth=oauth
    )


async def _collect_ui_contacts_tab_matches(
    tenant_slug: str,
    carrier_id: int,
    *,
    row_filter: Callable[[list[dict[str, Any]]], list[dict[str, Any]]],
    oauth: TurvoOAuthService | None = None,
) -> list[dict[str, Any]]:
    matched_rows: list[dict[str, Any]] = []
    seen_contact_ids: set[int] = set()
    start = 0

    for _ in range(_UI_CONTACTS_MAX_PAGES):
        payload = await _fetch_ui_contacts_tab(
            tenant_slug,
            carrier_id,
            start=start,
            page_size=_UI_CONTACTS_PAGE_SIZE,
            oauth=oauth,
        )
        rows = driver_rows_from_contacts_tab(payload)
        for row in row_filter(rows):
            cid = row.get("contact_id")
            if cid is None:
                continue
            try:
                key = int(cid)
            except (TypeError, ValueError):
                continue
            if key in seen_contact_ids:
                continue
            seen_contact_ids.add(key)
            matched_rows.append(row)

        page_items = (payload.get("contacts") or {}).get("data") or []
        if not isinstance(page_items, list) or len(page_items) < _UI_CONTACTS_PAGE_SIZE:
            break
        start += _UI_CONTACTS_PAGE_SIZE

    return matched_rows


async def _hydrate_ui_contact_rows(
    tenant_slug: str,
    matched_rows: list[dict[str, Any]],
    *,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    api = client or TurvoApiClient()
    out: list[dict[str, Any]] = []
    for row in matched_rows:
        contact_id = row.get("contact_id")
        if contact_id is None:
            continue
        hydrated = await get_driver_contact(tenant_slug, int(contact_id), client=api)
        if hydrated is not None:
            out.append(hydrated)
    return out


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
    """Search carrier driver contacts by phone via Turvo UI accounts contacts tab."""
    _ = carrier_name
    matched_rows = await _collect_ui_contacts_tab_matches(
        tenant_slug,
        carrier_id,
        row_filter=lambda rows: filter_driver_rows_by_phone(rows, phone=phone, name=name),
        oauth=oauth,
    )
    return await _hydrate_ui_contact_rows(
        tenant_slug, matched_rows, client=client
    )


async def search_carrier_driver_contacts_by_name(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    name: str,
    client: Optional[TurvoApiClient] = None,
    oauth: TurvoOAuthService | None = None,
) -> list[dict[str, Any]]:
    """Search carrier driver contacts by name via Turvo UI accounts contacts tab."""
    _ = carrier_name
    # ponytail: fallback when Public API pool misses; carrier directory is source of truth
    matched_rows = await _collect_ui_contacts_tab_matches(
        tenant_slug,
        carrier_id,
        row_filter=lambda rows: filter_driver_rows_by_name(rows, name=name),
        oauth=oauth,
    )
    return await _hydrate_ui_contact_rows(
        tenant_slug, matched_rows, client=client
    )
