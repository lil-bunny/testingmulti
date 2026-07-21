"""Appointment scheduling intake service tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.appointment_scheduling.intake_service import AppointmentSchedulingIntakeService


@pytest.fixture
def appointment_sheet(tmp_path: Path):
    import pandas as pd

    path = tmp_path / "appointments.xlsx"
    pd.DataFrame(
        [
            {
                "CUSTOMER": "Acme Foods",
                "APPOINTMENT MODE": "email",
                "CONTACT DETAILS(EMAILS)": "scheduling <acme@example.com>",
                "Transit time": "3 days",
            }
        ]
    ).to_excel(path, index=False)
    return str(path)


def test_intake_success(appointment_sheet):
    service = AppointmentSchedulingIntakeService()
    tenant_settings = {
        "appointment_scheduling": {
            "appointment_data_source": appointment_sheet,
            "ascend_email": "ascend@example.com",
            "ascend_password": "secret",
        }
    }
    turvo_shipment = {
        "details": {
            "customerOrder": [
                {
                    "customer": {"name": "Acme Foods", "id": "CUST-42"},
                    "externalIds": [{"idValue": "DIAMOND-RPN-99"}],
                    "items": [{"deliveryLocation": [{"name": "Acme Foods"}]}],
                }
            ]
        }
    }
    ascend_shipment = {
        "totalCharge": "$100.00",
        "totalMiles": 10,
        "proNumber": "PRO",
        "shipmentStops": [
            {"appointmentStart": "2026-07-01T10:00:00Z", "stopName": "P"},
            {"stopName": "D"},
        ],
    }
    with patch(
        "app.services.appointment_scheduling.intake_service.get_shipment_async",
        new=AsyncMock(return_value=turvo_shipment),
    ), patch(
        "app.services.appointment_scheduling.intake_service.login_ascend_api",
        return_value={"accessToken": "token"},
    ), patch(
        "app.services.appointment_scheduling.intake_service.fetched_shipment_details",
        return_value=ascend_shipment,
    ), patch(
        "app.services.appointment_scheduling.intake_service.get_loc_ref_for_ascend_slots",
        return_value=[{"warehouse": "WH-1"}],
    ):
        result = service.run_intake(
            tenant_slug="t3ra",
            tenant_settings=tenant_settings,
            payload={"shipment_id": "12345"},
        )

    assert result.ok is True
    assert result.customer_contact is not None
    assert result.customer_contact.email == "acme@example.com"
    assert result.reference_number == "DIAMOND-RPN-99"
    assert result.customer_name == "Acme Foods"


def test_intake_missing_recipient_email(appointment_sheet):
    service = AppointmentSchedulingIntakeService()
    tenant_settings = {
        "appointment_scheduling": {
            "appointment_data_source": appointment_sheet,
            "ascend_email": "ascend@example.com",
            "ascend_password": "secret",
        }
    }
    turvo_shipment = {
        "details": {
            "customerOrder": [
                {
                    "customer": {"name": "Unknown Customer", "id": "CUST-1"},
                    "externalIds": [{"idValue": "DIAMOND-RPN-1"}],
                    "items": [{"deliveryLocation": [{"name": "Unknown Customer"}]}],
                }
            ]
        }
    }
    with patch(
        "app.services.appointment_scheduling.intake_service.get_shipment_async",
        new=AsyncMock(return_value=turvo_shipment),
    ):
        result = service.run_intake(
            tenant_slug="t3ra",
            tenant_settings=tenant_settings,
            payload={"shipment_id": "12345"},
        )
    assert result.ok is False
    assert result.skip_reason == "missing_recipient_email"


def test_intake_success_from_google_sheets_url():
    service = AppointmentSchedulingIntakeService()
    google_url = (
        "https://docs.google.com/spreadsheets/d/"
        "1PqAPAFxGYNSiHUYzLtCNh-ezvpGPpq4W1C8D0PjComk/edit?usp=sharing"
    )
    tenant_settings = {
        "appointment_scheduling": {
            "appointment_data_source": google_url,
            "ascend_email": "ascend@example.com",
            "ascend_password": "secret",
        }
    }
    turvo_shipment = {
        "details": {
            "customerOrder": [
                {
                    "customer": {"name": "COSTCO #960 DEPOT SC", "id": "CUST-42"},
                    "externalIds": [{"idValue": "DIAMOND-RPN-99"}],
                    "items": [
                        {"deliveryLocation": [{"name": "COSTCO #960 DEPOT SC"}]},
                    ],
                }
            ]
        }
    }
    sheet_rows = [
        {
            "CUSTOMER": "COSTCO #960 DEPOT SC",
            "APPOINTMENT MODE": "email",
            "CONTACT DETAILS": "mitej@theagentic.ai",
            "TRANSIT TIME": "7 hrs 31 mins",
        }
    ]
    ascend_shipment = {
        "totalCharge": "$100.00",
        "totalMiles": 10,
        "proNumber": "PRO",
        "shipmentStops": [
            {"appointmentStart": "2026-07-01T10:00:00Z", "stopName": "P"},
            {"stopName": "D"},
        ],
    }
    with patch(
        "app.services.appointment_scheduling.intake_service.get_shipment_async",
        new=AsyncMock(return_value=turvo_shipment),
    ), patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_sheet_rows",
        return_value=sheet_rows,
    ), patch(
        "app.services.appointment_scheduling.intake_service.login_ascend_api",
        return_value={"accessToken": "token"},
    ), patch(
        "app.services.appointment_scheduling.intake_service.fetched_shipment_details",
        return_value=ascend_shipment,
    ), patch(
        "app.services.appointment_scheduling.intake_service.get_loc_ref_for_ascend_slots",
        return_value=[{"warehouse": "WH-1"}],
    ):
        result = service.run_intake(
            tenant_slug="t3ra",
            tenant_settings=tenant_settings,
            payload={"shipment_id": "12345"},
        )

    assert result.ok is True
    assert result.customer_contact is not None
    assert result.customer_contact.email == "mitej@theagentic.ai"
