"""Excel row → customer contact (email-only; ignores APPOINTMENT MODE)."""

from __future__ import annotations

import re
from typing import Any

from app.domain.appointment_scheduling.models import CustomerContactRow

_EMAIL_RE = re.compile(
    r"<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
)


def _normalize_customer(value: Any) -> str:
    return str(value or "").strip().lower()


def _extract_email(contact_details: Any) -> str | None:
    text = str(contact_details or "").strip()
    if not text:
        return None
    match = _EMAIL_RE.search(text)
    if not match:
        return None
    return (match.group(1) or match.group(2) or "").strip()


def _contact_details_value(row: dict[str, Any]) -> Any:
    for key in ("CONTACT DETAILS(EMAILS)", "CONTACT DETAILS"):
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _transit_time_value(row: dict[str, Any]) -> str:
    for key in ("Transit time", "Transit Time", "TRANSIT TIME"):
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def customer_contact_from_rows(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> CustomerContactRow | None:
    target = _normalize_customer(customer_name)
    if not target:
        return None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _normalize_customer(row.get("CUSTOMER")) != target:
            continue
        email = _extract_email(_contact_details_value(row))
        if not email:
            return None
        return CustomerContactRow(
            email=email,
            customer=str(row.get("CUSTOMER") or "").strip(),
            transit_time=_transit_time_value(row),
        )
    return None
