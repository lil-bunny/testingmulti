"""Appointment scheduling intake service tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.tenant_settings.t3ra import T3raAppointmentSchedulingSettings
from app.services.appointment_scheduling.intake_service import IntakeService


def _ascend_settings(**overrides) -> T3raAppointmentSchedulingSettings:
    data = {
        "appointment_data_source": "/tmp/x",
        "ascend_email": "ascend@example.com",
        "ascend_password": "secret",
    }
    data.update(overrides)
    return T3raAppointmentSchedulingSettings.model_validate(data)


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
    service = IntakeService()
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
        "app.services.appointment_scheduling.intake_service.load_appointment_scheduling_settings",
        return_value=_ascend_settings(appointment_data_source=appointment_sheet),
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


def test_intake_reuses_shipment_from_payload_without_turvo_fetch(appointment_sheet):
    service = IntakeService()
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
    turvo_mock = AsyncMock(return_value=turvo_shipment)
    with patch(
        "app.services.appointment_scheduling.intake_service.get_shipment_async",
        new=turvo_mock,
    ), patch(
        "app.services.appointment_scheduling.intake_service.load_appointment_scheduling_settings",
        return_value=_ascend_settings(appointment_data_source=appointment_sheet),
    ), patch(
        "app.services.appointment_scheduling.intake_service.login_ascend_api",
        return_value={"accessToken": "token"},
    ), patch(
        "app.services.appointment_scheduling.intake_service.fetched_shipment_details",
        return_value={
            "totalCharge": "$100.00",
            "totalMiles": 10,
            "proNumber": "PRO",
            "shipmentStops": [
                {"appointmentStart": "2026-07-01T10:00:00Z", "stopName": "P"},
                {"stopName": "D"},
            ],
        },
    ), patch(
        "app.services.appointment_scheduling.intake_service.get_loc_ref_for_ascend_slots",
        return_value=[{"warehouse": "WH-1"}],
    ):
        result = service.run_intake(
            tenant_slug="t3ra",
            tenant_settings=tenant_settings,
            payload={"shipment_id": "12345", "shipment": turvo_shipment},
        )

    assert result.ok is True
    turvo_mock.assert_not_called()


def test_intake_missing_recipient_email(appointment_sheet):
    service = IntakeService()
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
    assert result.failure is not None
    assert result.failure.code == "missing_recipient_email"


def test_intake_success_from_google_sheets_url():
    service = IntakeService()
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
        "app.services.appointment_scheduling.intake_service.load_appointment_scheduling_settings",
        return_value=_ascend_settings(appointment_data_source=google_url),
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


def test_intake_links_shipment_locations_when_shipments_row_id_present(appointment_sheet):
    link_svc = MagicMock()
    link_svc.try_link_from_turvo_shipment_payload.return_value = MagicMock(
        pickup_location_id="p-id",
        delivery_location_id="d-id",
    )
    service = IntakeService(location_link_service=link_svc)
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
                    "customer": {"name": "Acme Foods"},
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
        "app.services.appointment_scheduling.intake_service.load_appointment_scheduling_settings",
        return_value=_ascend_settings(appointment_data_source=appointment_sheet),
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
            payload={"shipment_id": "12345", "shipments_row_id": "ship-row-1"},
        )

    assert result.ok is True
    link_svc.try_link_from_turvo_shipment_payload.assert_called_once()
    state_patch = service.build_intake_state_patch(result)
    assert "customer_id" not in state_patch
    assert "shipment_location_link" not in state_patch
