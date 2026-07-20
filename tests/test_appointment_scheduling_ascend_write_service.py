"""Tests for AppointmentSchedulingAscendWriteService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.appointment_scheduling.ascend_write_service import (
    AppointmentSchedulingAscendWriteService,
)

_REF = "DIAMOND-RPN00008809"
_ISO = "2026-07-18T10:30:00"


def test_skip_ascend_writes_dry_run_no_http() -> None:
    svc = AppointmentSchedulingAscendWriteService()
    with patch(
        "app.services.appointment_scheduling.ascend_write_service.login_ascend_api"
    ) as login_mock:
        result = svc.apply_dropoff(
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": True}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )

    login_mock.assert_not_called()
    assert result.ok is True
    assert result.skipped is True
    assert result.dry_run is True
    assert result.payload is not None


def test_live_ascend_put_when_writes_enabled() -> None:
    svc = AppointmentSchedulingAscendWriteService()
    shipment = {
        "shipmentStops": [
            {"id": "stop-1", "stopNumber": "1"},
            {"id": "stop-2", "stopNumber": "2"},
        ]
    }
    with (
        patch(
            "app.services.appointment_scheduling.ascend_write_service.skip_ascend_writes_enabled",
            return_value=False,
        ),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.login_ascend_api",
            return_value={"accessToken": "token"},
        ),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.fetched_shipment_details",
            return_value=shipment,
        ),
        patch(
            "app.services.appointment_scheduling.ascend_write_service.update_shipment_stops",
            return_value={"ok": True},
        ) as put_mock,
    ):
        result = svc.apply_dropoff(
            tenant_settings={
                "appointment_scheduling": {
                    "skip_ascend_writes": False,
                    "ascend_email": "user@example.com",
                    "ascend_password": "secret",
                }
            },
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )

    assert result.ok is True
    assert result.skipped is False
    put_mock.assert_called_once()
    assert put_mock.call_args.kwargs["payload"]["shipmentStops"][0]["id"] == "stop-2"


def test_missing_credentials_when_writes_enabled() -> None:
    svc = AppointmentSchedulingAscendWriteService()
    with patch(
        "app.services.appointment_scheduling.ascend_write_service.skip_ascend_writes_enabled",
        return_value=False,
    ):
        result = svc.apply_dropoff(
            tenant_settings={"appointment_scheduling": {"skip_ascend_writes": False}},
            reference_number=_REF,
            appointment_start_iso=_ISO,
        )
    assert result.ok is False
    assert result.error == "missing_ascend_credentials"
