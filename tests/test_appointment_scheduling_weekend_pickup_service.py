"""Tests for AppointmentSchedulingWeekendPickupService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.appointment_scheduling.weekend_pickup_service import (
    AppointmentSchedulingWeekendPickupService,
)


def _state(**overrides):
    data = {
        "tenant_slug": "t3ra",
        "shipment_id": "1000324895",
        "reference_number": "DIAMOND-RPN1",
        "tenant_settings": {"appointment_scheduling": {}},
        "llm_scheduling_decision": {
            "weekend_shifted": True,
            "selected_pickup_date": "2026-07-01",
            "selected_pickup_time": "08:00",
        },
        "ascend_context": {
            "appointments": [
                {
                    "appointmentId": "appt-1",
                    "stopNumber": 1,
                    "startTime": "2026-06-28T08:00:00",
                    "endTime": "2026-06-28T09:00:00",
                }
            ]
        },
        "shipment": {
            "details": {
                "globalRoute": [
                    {
                        "deleted": False,
                        "name": "Pickup WH",
                        "stopType": {"value": "pickup"},
                        "appointment": {},
                    }
                ]
            }
        },
    }
    data.update(overrides)
    return SimpleNamespace(data=data)


def test_skipped_when_not_weekend_shifted() -> None:
    state = _state(
        llm_scheduling_decision={
            "weekend_shifted": False,
            "selected_pickup_date": "2026-07-01",
            "selected_pickup_time": "08:00",
        }
    )
    result = AppointmentSchedulingWeekendPickupService().apply_from_state(state)
    assert result.ok is True
    assert result.skipped is True


@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.skip_ascend_writes_enabled",
    return_value=False,
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.update_stop_appointment_time",
    new_callable=AsyncMock,
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.update_appointment",
    return_value={"success": True},
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.login_ascend_api",
    return_value={"accessToken": "token"},
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.load_appointment_scheduling_settings",
)
def test_applies_ascend_and_turvo_when_changed(
    mock_load_settings: MagicMock,
    _login: MagicMock,
    _update_appt: MagicMock,
    mock_turvo_update: AsyncMock,
    _skip_writes: MagicMock,
) -> None:
    mock_load_settings.return_value = MagicMock(
        ascend_email="a@b.com",
        ascend_password="secret",
    )
    mock_turvo_update.return_value = {
        "ok": True,
        "updated": True,
        "stop_name": "Pickup WH",
    }

    result = AppointmentSchedulingWeekendPickupService().apply_from_state(_state())

    assert result.ok is True
    assert result.skipped is False
    assert result.ascend_updated is True
    assert result.turvo_updated is True
    assert result.turvo_pickup_start_time == "2026-07-01 08:00:00"


@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.skip_ascend_writes_enabled",
    return_value=True,
)
def test_dry_run_when_skip_ascend_writes(_skip: MagicMock) -> None:
    result = AppointmentSchedulingWeekendPickupService().apply_from_state(_state())
    assert result.ok is True
    assert result.skipped is True
    assert result.dry_run is True
