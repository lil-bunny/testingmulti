"""Excel row → customer contact (pure parsing; APPOINTMENT MODE enforced at service gate)."""

from __future__ import annotations

import re
from typing import Any

from app.domain.appointment_scheduling.models import CustomerContactRow

_EMAIL_RE = re.compile(
    r"<([^>]+)>|([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})"
)


def _normalize_customer(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_appointment_mode(raw: Any) -> str:
    return str(raw or "").strip().lower()


def is_email_appointment_mode(mode: str) -> bool:
    return mode == "email"


def appointment_mode_from_row(row: dict[str, Any]) -> str:
    for key in ("APPOINTMENT MODE", "Appointment Mode"):
        if key in row and row.get(key) not in (None, ""):
            return normalize_appointment_mode(row.get(key))
    return ""


def find_customer_sheet_row(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> dict[str, Any] | None:
    """Return the sheet row for ``customer_name``.

    When a customer has multiple rows (e.g. a portal row above an email row),
    prefer the ``APPOINTMENT MODE = email`` row so a non-email row does not
    shadow the email one. Falls back to the first CUSTOMER match otherwise.
    """
    target = _normalize_customer(customer_name)
    if not target:
        return None
    first_match: dict[str, Any] | None = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _normalize_customer(row.get("CUSTOMER")) != target:
            continue
        if first_match is None:
            first_match = row
        if is_email_appointment_mode(appointment_mode_from_row(row)):
            return row
    return first_match


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


def customer_contact_from_row(row: dict[str, Any]) -> CustomerContactRow | None:
    email = _extract_email(_contact_details_value(row))
    if not email:
        return None
    return CustomerContactRow(
        email=email,
        customer=str(row.get("CUSTOMER") or "").strip(),
        transit_time=_transit_time_value(row),
    )


def customer_contact_from_rows(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> CustomerContactRow | None:
    row = find_customer_sheet_row(rows, customer_name)
    if row is None:
        return None
    return customer_contact_from_row(row)
