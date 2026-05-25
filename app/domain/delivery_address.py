"""Map Delivery locations sheet rows to tender ``delivery_address`` JSON payloads."""

from __future__ import annotations

import re
from typing import Any, Callable

from app.domain.delivery_locations import (
    DeliveryLocationsIndex,
    clean_cell_value,
    normalize_delivery_number,
)
from app.integrations.pgeocode.state_lookup import lookup_state

# Delivery locations sheet column names (source spreadsheet headers).
_SHEET_NAME = "Name"
_SHEET_NAME2 = "Name2"
_SHEET_STREET = "Street"
_SHEET_STREET2 = "Street 2"
_SHEET_CITY = "City"
_SHEET_ZIP = "Zip Code"
_SHEET_COUNTRY = "country name"

# (country_name, postal_code) -> state name (or None when unresolved).
StateResolver = Callable[[str | None, object], str | None]


def _required_str(val: Any) -> str:
    cleaned = clean_cell_value(val)
    if cleaned is None:
        return ""
    return str(cleaned)


def _optional_str(val: Any) -> str | None:
    cleaned = clean_cell_value(val)
    if cleaned is None:
        return None
    return str(cleaned)


def _resolve_state(
    country: str,
    postal: str,
    state_resolver: StateResolver | None,
) -> str:
    if state_resolver is None:
        return ""
    resolved = state_resolver(country or None, postal or None)
    if not resolved:
        return ""
    return str(resolved).strip() or ""


def delivery_address_from_location_row(
    location_row: dict[str, Any],
    *,
    state_resolver: StateResolver | None = None,
) -> dict[str, Any]:
    """Build normalized ``delivery_address`` JSON from one Delivery locations row.

    When ``state_resolver`` is provided, ``state`` is filled by calling it with
    the cleaned country name and postal code; if the resolver returns ``None``
    or a blank value, ``state`` falls back to ``""`` to preserve the existing
    contract.
    """
    country = _required_str(location_row.get(_SHEET_COUNTRY))
    postal = _required_str(location_row.get(_SHEET_ZIP))
    state = _resolve_state(country, postal, state_resolver)
    return {
        "name": _required_str(location_row.get(_SHEET_NAME)),
        "name2": _optional_str(location_row.get(_SHEET_NAME2)),
        "address1": _required_str(location_row.get(_SHEET_STREET)),
        "address2": _optional_str(location_row.get(_SHEET_STREET2)),
        "city": _required_str(location_row.get(_SHEET_CITY)),
        "state": state,
        "postal_code": postal,
        "country": country,
    }


def resolve_delivery_address(
    delivery_code: Any,
    index: DeliveryLocationsIndex | None,
    *,
    state_resolver: StateResolver | None = None,
) -> dict[str, Any] | None:
    """
    Look up ``delivery_code`` in ``index`` and return ``delivery_address`` JSON.

    Returns ``None`` when the code is blank, ``index`` is missing, or no row matches.
    When ``state_resolver`` is provided, it is invoked once per resolved row.
    """
    if index is None:
        return None
    key = normalize_delivery_number(delivery_code)
    if not key:
        return None
    location_row = index.lookup(key)
    if location_row is None:
        return None
    return delivery_address_from_location_row(
        location_row, state_resolver=state_resolver
    )


def _line_str(val: Any) -> str:
    cleaned = clean_cell_value(val)
    if cleaned is None:
        return ""
    return str(cleaned).strip()


def _optional_line(val: Any) -> str | None:
    s = _line_str(val)
    return s if s else None


def _postal_for_usps_line(postal: str) -> str:
    s = (postal or "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    s = s.replace(" ", "")
    zip4 = re.match(r"^(\d{5})-(\d{1,4})$", s)
    if zip4:
        return f"{zip4.group(1)}-{zip4.group(2)}"
    digits = re.sub(r"\D", "", s)
    if len(digits) >= 5:
        return digits[:5]
    return s


def format_usps_mailing_address(addr: dict[str, Any] | None) -> str:
    """
    Format structured address JSON into a multi-line USPS-style mailing block.

    Used for Gelita tender email pickup (static config) and delivery (``tenders.delivery_address``).
    """
    if not addr or not isinstance(addr, dict):
        return ""

    lines: list[str] = []
    name = _line_str(addr.get("name"))
    if name:
        lines.append(name)
    name2 = _optional_line(addr.get("name2"))
    if name2:
        lines.append(name2)

    address1 = _line_str(addr.get("address1"))
    if address1:
        lines.append(address1)
    address2 = _optional_line(addr.get("address2"))
    if address2:
        lines.append(address2)

    city = _line_str(addr.get("city")).upper()
    postal_raw = _line_str(addr.get("postal_code"))
    postal = _postal_for_usps_line(postal_raw)
    state = (lookup_state(addr.get("country"), postal_raw) or "").strip()
    if not state:
        state_raw = _line_str(addr.get("state"))
        if len(state_raw) == 2 and state_raw.isalpha():
            state = state_raw.upper()
        else:
            state = state_raw

    if city or state or postal:
        csz_parts = [p for p in (city, state, postal) if p]
        lines.append(" ".join(csz_parts))

    return "\n".join(lines)
