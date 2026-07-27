"""Unit tests for appointment scheduling recipient contact gate."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.error_catalog import BusinessError
from app.services.appointment_scheduling.intake_service import (
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


def _shipment_payload(
    *,
    delivery_stop_name: str = "Acme Corp",
    billing_customer_name: str = "Acme Corp",
) -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": billing_customer_name, "id": "CUST-1"},
                    "items": [
                        {"deliveryLocation": [{"name": delivery_stop_name}]},
                    ],
                }
            ]
        }
    }


def _email_row(**overrides: object) -> dict:
    row = {
        "CUSTOMER": "Acme Corp",
        "APPOINTMENT MODE": "email",
        "CONTACT DETAILS(EMAILS)": "ops@acme.example",
    }
    row.update(overrides)
    return row


def test_contact_from_rows_skip_reason_returns_none_when_email_found() -> None:
    assert contact_from_rows_skip_reason([_email_row()], "Acme Corp") is None


def test_contact_from_rows_skip_reason_missing_recipient_email() -> None:
    rows = [{"CUSTOMER": "Other Customer", "CONTACT DETAILS(EMAILS)": "x@y.com"}]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == BusinessError.MISSING_RECIPIENT_EMAIL


def test_contact_from_rows_skip_reason_portal_mode_with_email() -> None:
    rows = [
        _email_row(
            **{
                "APPOINTMENT MODE": "portal",
                "CONTACT DETAILS(EMAILS)": "ops@acme.example",
            }
        )
    ]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == BusinessError.APPOINTMENT_MODE_NOT_EMAIL


def test_contact_from_rows_skip_reason_call_mode_phone_only() -> None:
    rows = [
        {
            "CUSTOMER": "Acme Corp",
            "APPOINTMENT MODE": "call",
            "CONTACT DETAILS(CALLS)": "555-123-4567",
        }
    ]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == BusinessError.APPOINTMENT_MODE_NOT_EMAIL


def test_contact_from_rows_skip_reason_blank_mode_with_email() -> None:
    rows = [
        {
            "CUSTOMER": "Acme Corp",
            "CONTACT DETAILS(EMAILS)": "ops@acme.example",
        }
    ]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == BusinessError.APPOINTMENT_MODE_NOT_EMAIL


def test_contact_from_rows_skip_reason_email_mode_no_email() -> None:
    rows = [{"CUSTOMER": "Acme Corp", "APPOINTMENT MODE": "email"}]
    assert contact_from_rows_skip_reason(rows, "Acme Corp") == BusinessError.MISSING_RECIPIENT_EMAIL


def test_missing_recipient_email_skip_reason_resolves_contact() -> None:
    with patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_customer_rows",
        return_value=[_email_row()],
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
        "app.services.appointment_scheduling.intake_service.load_appointment_customer_rows",
        return_value=rows,
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=_shipment_payload(),
            )
            == BusinessError.MISSING_RECIPIENT_EMAIL.value
        )


def test_missing_recipient_email_skip_reason_empty_sheet_source() -> None:
    settings = _tenant_settings(sheet_source="")
    assert (
        missing_recipient_email_skip_reason(
            tenant_settings=settings,
            shipment_payload=_shipment_payload(),
        )
        == BusinessError.MISSING_APPOINTMENT_DATA_SOURCE.value
    )


def test_missing_recipient_email_skip_reason_sheet_load_error() -> None:
    with patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_customer_rows",
        side_effect=OSError("missing file"),
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=_shipment_payload(),
            )
            == BusinessError.APPOINTMENT_SHEET_UNREADABLE.value
        )


def test_missing_recipient_email_uses_delivery_stop_not_billing_customer() -> None:
    rows = [
        {
            "CUSTOMER": "PETCO DC 810",
            "APPOINTMENT MODE": "email",
            "CONTACT DETAILS(EMAILS)": "ops@example.com",
        }
    ]
    payload = _shipment_payload(
        delivery_stop_name="PETCO DC 810",
        billing_customer_name="DIAMOND PET FOODS",
    )
    with patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_customer_rows",
        return_value=rows,
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=payload,
            )
            is None
        )


def test_missing_recipient_email_billing_customer_only_does_not_match() -> None:
    rows = [
        {
            "CUSTOMER": "PETCO DC 810",
            "APPOINTMENT MODE": "email",
            "CONTACT DETAILS(EMAILS)": "ops@example.com",
        }
    ]
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "PETCO DC 810", "id": "CUST-1"},
                }
            ]
        }
    }
    with patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_customer_rows",
        return_value=rows,
    ):
        assert (
            missing_recipient_email_skip_reason(
                tenant_settings=_tenant_settings(),
                shipment_payload=payload,
            )
            == BusinessError.MISSING_RECIPIENT_EMAIL.value
        )
