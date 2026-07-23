"""Recipient email pre-check for appointment scheduling ingress and intake."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.skip_reasons import (
    SKIP_APPOINTMENT_MODE_NOT_EMAIL,
    SKIP_APPOINTMENT_SHEET_UNREADABLE,
    SKIP_MISSING_APPOINTMENT_DATA_SOURCE,
    SKIP_MISSING_RECIPIENT_EMAIL,
)
from app.domain.appointment_scheduling.models import CustomerContactRow
from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.google.sheets import GoogleSheetsError
from app.integrations.turvo.shipments import delivery_stop_name_from_payload
from app.services.appointment_scheduling.sheet_loader import load_appointment_sheet_rows
from app.tools.appointment_scheduling.customer_contact import (
    appointment_mode_from_row,
    customer_contact_from_row,
    find_customer_sheet_row,
    is_email_appointment_mode,
)

MISSING_RECIPIENT_EMAIL = SKIP_MISSING_RECIPIENT_EMAIL
MISSING_APPOINTMENT_DATA_SOURCE = SKIP_MISSING_APPOINTMENT_DATA_SOURCE
APPOINTMENT_SHEET_UNREADABLE = SKIP_APPOINTMENT_SHEET_UNREADABLE
APPOINTMENT_MODE_NOT_EMAIL = SKIP_APPOINTMENT_MODE_NOT_EMAIL


def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
    raw = tenant_settings.get("appointment_scheduling") or {}
    if isinstance(raw, T3raAppointmentSchedulingSettings):
        return raw
    return T3raAppointmentSchedulingSettings.model_validate(raw)


def contact_from_rows_skip_reason(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> str | None:
    row = find_customer_sheet_row(rows, customer_name)
    if row is None:
        return MISSING_RECIPIENT_EMAIL
    if not is_email_appointment_mode(appointment_mode_from_row(row)):
        return APPOINTMENT_MODE_NOT_EMAIL
    contact = customer_contact_from_row(row)
    if contact is None or not contact.email:
        return MISSING_RECIPIENT_EMAIL
    return None


def missing_recipient_email_skip_reason(
    *,
    tenant_settings: dict[str, Any],
    shipment_payload: dict[str, Any],
) -> str | None:
    """Return a skip reason when sheet/recipient pre-check fails; else None."""
    skip_reason, _contact = resolve_recipient_contact(
        tenant_settings=tenant_settings,
        shipment_payload=shipment_payload,
    )
    return skip_reason


def resolve_recipient_contact(
    *,
    tenant_settings: dict[str, Any],
    shipment_payload: dict[str, Any],
) -> tuple[str | None, CustomerContactRow | None]:
    """Load appointment sheet once; return skip reason or resolved contact."""
    settings = _settings(tenant_settings)
    sheet_source = str(settings.appointment_data_source or "").strip()
    if not sheet_source:
        return MISSING_APPOINTMENT_DATA_SOURCE, None
    try:
        rows = load_appointment_sheet_rows(sheet_source)
    except (OSError, GoogleSheetsError, ValueError):
        return APPOINTMENT_SHEET_UNREADABLE, None

    sheet_customer = delivery_stop_name_from_payload(shipment_payload) or ""
    if skip := contact_from_rows_skip_reason(rows, sheet_customer):
        return skip, None
    row = find_customer_sheet_row(rows, sheet_customer)
    contact = customer_contact_from_row(row) if row is not None else None
    if contact is None or not contact.email:
        return MISSING_RECIPIENT_EMAIL, None
    return None, contact
