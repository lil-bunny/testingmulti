"""Recipient email pre-check for appointment scheduling ingress and intake."""

from __future__ import annotations

from typing import Any

from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.integrations.google.sheets import GoogleSheetsError
from app.services.appointment_scheduling.sheet_loader import load_appointment_sheet_rows
from app.tools.appointment_scheduling.customer_contact import customer_contact_from_rows
from app.tools.appointment_scheduling.ingress import customer_name_from_turvo_shipment

MISSING_RECIPIENT_EMAIL = "missing_recipient_email"
MISSING_APPOINTMENT_DATA_SOURCE = "missing_appointment_data_source"
APPOINTMENT_SHEET_UNREADABLE = "appointment_sheet_unreadable"


def _settings(tenant_settings: dict[str, Any]) -> T3raAppointmentSchedulingSettings:
    raw = tenant_settings.get("appointment_scheduling") or {}
    if isinstance(raw, T3raAppointmentSchedulingSettings):
        return raw
    return T3raAppointmentSchedulingSettings.model_validate(raw)


def contact_from_rows_skip_reason(
    rows: list[dict[str, Any]],
    customer_name: str,
) -> str | None:
    contact = customer_contact_from_rows(rows, customer_name)
    if contact is None or not contact.email:
        return MISSING_RECIPIENT_EMAIL
    return None


def missing_recipient_email_skip_reason(
    *,
    tenant_settings: dict[str, Any],
    shipment_payload: dict[str, Any],
) -> str | None:
    """Return a skip reason when sheet/recipient pre-check fails; else None."""
    settings = _settings(tenant_settings)
    sheet_source = str(settings.appointment_data_source or "").strip()
    if not sheet_source:
        return MISSING_APPOINTMENT_DATA_SOURCE
    try:
        rows = load_appointment_sheet_rows(sheet_source)
    except (OSError, GoogleSheetsError, ValueError):
        return APPOINTMENT_SHEET_UNREADABLE

    customer_name = customer_name_from_turvo_shipment(shipment_payload) or ""
    return contact_from_rows_skip_reason(rows, customer_name)
