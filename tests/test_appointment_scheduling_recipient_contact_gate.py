"""Unit tests for appointment scheduling recipient contact gate."""

from __future__ import annotations

from unittest.mock import patch

from app.services.appointment_scheduling.recipient_contact_gate import (
    APPOINTMENT_SHEET_UNREADABLE,
    MISSING_APPOINTMENT_DATA_SOURCE,
    MISSING_RECIPIENT_EMAIL,
    contact_from_rows_skip_reason,
    missing_recipient_email_skip_reason,
)
from tests.fixtures.t3ra_tenant_settings import minimal_t3ra_tenant_settings


def _tenant_settings(*, sheet_source: str = "/tmp/appointments.xlsx") -> dict:
    settings = minimal_t3ra_tenant_settings()
    settings["appointment_scheduling"] = {
        **(settings.get("appointment_scheduling") or {}),
        "appointment_data_source": sheet_source,
    }
    return settings


def _shipment_payload(*, customer_name: str = "Acme Corp") -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": customer_name, "id": "CUST-1"},
                }
            ]
        }
    }


def test_contact_from_rows_skip_reason_returns_none_when_email_found() -> None:
    rows = [
        {
            "CUSTOMER": "Acme Corp",
            "CONTACT DETAILS(EMAILS)": "ops@acme.example",
        }
    ]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") is None


def test_contact_from_rows_skip_reason_missing_recipient_email() -> None:
    rows = [{"CUSTOMER": "Other Customer", "CONTACT DETAILS(EMAILS)": "x@y.com"}]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == MISSING_RECIPIENT_EMAIL


def test_missing_recipient_email_skip_reason_resolves_contact() -> None:
    rows = [
        {
            "CUSTOMER": "Acme Corp",
            "CONTACT DETAILS(EMAILS)": "ops@acme.example",
        }
    ]
    with patch(
        "app.services.appointment_scheduling.recipient_contact_gate.load_appointment_sheet_rows",
        return_value=rows,
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=_shipment_payload(),
            )
            is None
        )


def test_missing_recipient_email_skip_reason_unknown_customer() -> None:
    rows = [{"CUSTOMER": "Other Customer", "CONTACT DETAILS(EMAILS)": "x@y.com"}]
    with patch(
        "app.services.appointment_scheduling.recipient_contact_gate.load_appointment_sheet_rows",
        return_value=rows,
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=_shipment_payload(),
            )
            == MISSING_RECIPIENT_EMAIL
        )


def test_missing_recipient_email_skip_reason_empty_sheet_source() -> None:
    settings = _tenant_settings(sheet_source="")
    assert (
        missing_recipient_email_skip_reason(
            tenant_settings=settings,
            shipment_payload=_shipment_payload(),
        )
        == MISSING_APPOINTMENT_DATA_SOURCE
    )


def test_missing_recipient_email_skip_reason_sheet_load_error() -> None:
    with patch(
        "app.services.appointment_scheduling.recipient_contact_gate.load_appointment_sheet_rows",
        side_effect=OSError("missing file"),
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=_shipment_payload(),
            )
            == APPOINTMENT_SHEET_UNREADABLE
        )
