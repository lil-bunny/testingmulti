"""Turvo Public API contact list/create (outbound)."""

from __future__ import annotations

from typing import Any, Optional

from app.integrations.turvo.public_api_client import TurvoApiClient, TurvoApiError
from app.integrations.turvo.shipments import driver_contact_ids_from_shipment
from app.tools.driver_details import (
    emails_match,
    names_match,
    normalize_phone_digits,
    phones_match,
)

DRIVER_ROLE = {"key": "1993", "value": "Driver"}
PHONE_TYPE = {"key": "1001", "value": "Work"}
EMAIL_TYPE = {"key": "1051", "value": "Work"}
PHONE_COUNTRY_US = {"key": "us", "value": "+1"}


def _contact_carrier_ids(contact: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for key in ("context", "associations"):
        items = contact.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            if raw_id is not None and str(raw_id).strip():
                ids.add(str(raw_id).strip())
    return ids


def contact_linked_to_carrier(
    contact: dict[str, Any],
    *,
    carrier_id: int | str,
    carrier_name: str | None = None,
) -> bool:
    cid = str(carrier_id).strip()
    if cid in _contact_carrier_ids(contact):
        return True
    if not carrier_name:
        return False
    name_lower = carrier_name.strip().lower()
    for key in ("context", "associations"):
        items = contact.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("type") or "").upper() == "CARRIER" and str(
                item.get("name") or ""
            ).strip().lower() == name_lower:
                return True
    return False


def _parse_contact_row(raw: dict[str, Any]) -> dict[str, Any]:
    phones: list[str] = []
    for p in raw.get("phones") or raw.get("phone") or []:
        if isinstance(p, dict) and p.get("number"):
            phones.append(str(p["number"]))
    emails: list[str] = []
    for e in raw.get("emails") or raw.get("email") or []:
        if isinstance(e, dict) and e.get("email"):
            emails.append(str(e["email"]))
    return {
        "id": raw.get("id"),
        "name": raw.get("name"),
        "phones": phones,
        "emails": emails,
        "raw": raw,
    }


async def list_driver_contacts(
    tenant_slug: str,
    *,
    name: str | None = None,
    email: str | None = None,
    page_size: int = 25,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    """GET /contacts/list first page; driver role filtered client-side."""
    listed = await _paginate_contacts_list(
        tenant_slug,
        name=name,
        email=email,
        page_size=page_size,
        max_pages=1,
        client=client,
    )
    return [row for row in listed if _is_driver_role(row["raw"])]


def _is_driver_role(raw: dict[str, Any]) -> bool:
    roles = raw.get("role") or []
    if not isinstance(roles, list):
        return False
    for role in roles:
        if not isinstance(role, dict):
            continue
        if role.get("key") == DRIVER_ROLE["key"]:
            return True
        if str(role.get("value") or "").strip().lower() == "driver":
            return True
    return False


def _merge_contact_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for row in rows:
        cid = row.get("id")
        if cid is None:
            continue
        try:
            key = int(cid)
        except (TypeError, ValueError):
            continue
        if key not in merged:
            merged[key] = row
    return list(merged.values())


async def get_driver_contact(
    tenant_slug: str,
    contact_id: int,
    *,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any] | None:
    """GET /contacts/{id} — normalized driver contact row."""
    api = client or TurvoApiClient()
    try:
        payload = await api.request(tenant_slug, "GET", f"/contacts/{contact_id}")
    except TurvoApiError:
        return None
    details = payload.get("details") if isinstance(payload, dict) else None
    raw = details if isinstance(details, dict) else payload
    if not isinstance(raw, dict):
        return None
    return _parse_contact_row(raw)


async def _paginate_contacts_list(
    tenant_slug: str,
    *,
    name: str | None = None,
    email: str | None = None,
    page_size: int = 100,
    max_pages: int = 5,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    """GET /contacts/list without role filter; capped at max_pages * page_size."""
    api = client or TurvoApiClient()
    out: list[dict[str, Any]] = []
    start = 0
    for _ in range(max_pages):
        params: dict[str, Any] = {
            "pageSize": str(page_size),
            "start": str(start),
        }
        if name and name.strip():
            params["name[eq]"] = name.strip()
        if email and email.strip():
            params["email[eq]"] = email.strip()
        payload = await api.request(tenant_slug, "GET", "/contacts/list", params=params)
        details = payload.get("details") if isinstance(payload, dict) else None
        contacts = details.get("contacts") if isinstance(details, dict) else None
        if not isinstance(contacts, list) or not contacts:
            break
        batch = [_parse_contact_row(c) for c in contacts if isinstance(c, dict)]
        out.extend(batch)
        if len(contacts) < page_size:
            break
        start += page_size
    return out


async def _paginate_driver_contacts(
    tenant_slug: str,
    *,
    name: str | None = None,
    email: str | None = None,
    page_size: int = 100,
    max_pages: int = 5,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    listed = await _paginate_contacts_list(
        tenant_slug,
        name=name,
        email=email,
        page_size=page_size,
        max_pages=max_pages,
        client=client,
    )
    return [row for row in listed if _is_driver_role(row["raw"])]


async def _paginate_carrier_driver_contacts(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    name: str | None = None,
    email: str | None = None,
    page_size: int = 100,
    max_pages: int = 5,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    listed = await _paginate_contacts_list(
        tenant_slug,
        name=name,
        email=email,
        page_size=page_size,
        max_pages=max_pages,
        client=client,
    )
    out: list[dict[str, Any]] = []
    for row in listed:
        raw = row.get("raw")
        if not isinstance(raw, dict):
            continue
        if not _is_driver_role(raw):
            continue
        if contact_linked_to_carrier(
            raw, carrier_id=carrier_id, carrier_name=carrier_name
        ):
            out.append(row)
    return out


async def _driver_contacts_from_carrier(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    api = client or TurvoApiClient()
    try:
        payload = await api.request(
            tenant_slug,
            "GET",
            f"/carriers/{carrier_id}",
            params={"fullResponse": "true"},
        )
    except TurvoApiError:
        return []
    details = payload.get("details") if isinstance(payload, dict) else None
    carrier = details if isinstance(details, dict) else payload
    if not isinstance(carrier, dict):
        return []
    embedded = carrier.get("contacts") or []
    if not isinstance(embedded, list):
        return []
    out: list[dict[str, Any]] = []
    for item in embedded:
        if not isinstance(item, dict):
            continue
        contact = item.get("contact") if isinstance(item.get("contact"), dict) else item
        if not isinstance(contact, dict):
            continue
        cid = contact.get("id")
        if cid is None:
            continue
        row = _parse_contact_row(contact)
        if not _is_driver_role(row["raw"]):
            hydrated = await get_driver_contact(tenant_slug, int(cid), client=api)
            if hydrated is not None:
                row = hydrated
        if not _is_driver_role(row["raw"]):
            continue
        if contact_linked_to_carrier(
            row["raw"], carrier_id=carrier_id, carrier_name=carrier_name
        ):
            out.append(row)
    return out


async def list_carrier_driver_contacts(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    shipment_payload: dict[str, Any] | None = None,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    """Merge driver contacts for a carrier from list, carrier embed, and shipment refs."""
    api = client or TurvoApiClient()
    rows: list[dict[str, Any]] = []

    rows.extend(
        await _paginate_carrier_driver_contacts(
            tenant_slug,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            client=api,
        )
    )

    rows.extend(
        await _driver_contacts_from_carrier(
            tenant_slug,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            client=api,
        )
    )

    if isinstance(shipment_payload, dict):
        for contact_id in driver_contact_ids_from_shipment(
            shipment_payload, carrier_id=carrier_id
        ):
            hydrated = await get_driver_contact(tenant_slug, contact_id, client=api)
            if hydrated is None or not _is_driver_role(hydrated["raw"]):
                continue
            if contact_linked_to_carrier(
                hydrated["raw"],
                carrier_id=carrier_id,
                carrier_name=carrier_name,
            ):
                rows.append(hydrated)

    return _merge_contact_rows(rows)


async def search_carrier_driver_contacts(
    tenant_slug: str,
    *,
    carrier_id: int,
    carrier_name: str,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    shipment_payload: dict[str, Any] | None = None,
    client: Optional[TurvoApiClient] = None,
) -> list[dict[str, Any]]:
    """Search merged carrier driver pool; filters are ANDed when multiple are set."""
    pool = await list_carrier_driver_contacts(
        tenant_slug,
        carrier_id=carrier_id,
        carrier_name=carrier_name,
        shipment_payload=shipment_payload,
        client=client,
    )
    matches = pool
    if name and str(name).strip():
        matches = [row for row in matches if names_match(name, row.get("name"))]
    if phone and normalize_phone_digits(phone):
        matches = [
            row
            for row in matches
            if any(phones_match(phone, p) for p in row.get("phones") or [])
        ]
    if email and str(email).strip():
        matches = [
            row
            for row in matches
            if any(emails_match(email, e) for e in row.get("emails") or [])
        ]
    return matches


def filter_contacts_for_carrier(
    contacts: list[dict[str, Any]],
    *,
    carrier_id: int,
    carrier_name: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in contacts:
        raw = row.get("raw")
        if isinstance(raw, dict) and contact_linked_to_carrier(
            raw, carrier_id=carrier_id, carrier_name=carrier_name
        ):
            out.append(row)
    return out


def filter_contacts_by_phone(
    contacts: list[dict[str, Any]], phone: str | None
) -> list[dict[str, Any]]:
    if not normalize_phone_digits(phone):
        return []
    return [
        row
        for row in contacts
        if any(phones_match(phone, p) for p in row.get("phones") or [])
    ]


def turvo_phone_number(raw_phone: str | None) -> str:
    """Store number without country prefix (Turvo sandbox shape)."""
    digits = normalize_phone_digits(raw_phone)
    if len(digits) == 11 and digits.startswith("1"):
        return digits[1:]
    return digits


async def create_driver_contact(
    tenant_slug: str,
    *,
    name: str,
    phone: str | None,
    email: str | None,
    carrier_id: int,
    carrier_name: str,
    client: Optional[TurvoApiClient] = None,
) -> int:
    """POST /contacts — create driver linked to carrier (email optional)."""
    api = client or TurvoApiClient()
    body: dict[str, Any] = {
        "name": name.strip(),
        "role": [DRIVER_ROLE],
        "context": [
            {
                "id": str(carrier_id),
                "name": carrier_name,
                "type": "CARRIER",
            }
        ],
    }
    cleaned_email = (email or "").strip()
    if cleaned_email:
        body["email"] = [
            {
                "email": cleaned_email,
                "isPrimary": True,
                "type": EMAIL_TYPE,
            }
        ]
    number = turvo_phone_number(phone)
    if number:
        body["phone"] = [
            {
                "number": number,
                "isPrimary": True,
                "type": PHONE_TYPE,
                "country": PHONE_COUNTRY_US,
            }
        ]
    payload = await api.request(
        tenant_slug,
        "POST",
        "/contacts",
        params={"fullResponse": "true"},
        json_body=body,
    )
    details = payload.get("details") if isinstance(payload, dict) else None
    contact_id = details.get("id") if isinstance(details, dict) else None
    if contact_id is None:
        raise ValueError("Turvo createContact returned no contact id")
    return int(contact_id)
