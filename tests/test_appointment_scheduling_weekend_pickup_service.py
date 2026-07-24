"""Tests for WeekendPickupService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.appointment_scheduling.weekend_pickup_service import (
    WeekendPickupService,
)


def _state(**overrides):
    data = {
        "tenant_slug": "t3ra",
        "tenant_id": "tenant-uuid-1",
        "workflow_lifecycle_id": "wl-1",
        "execution_id": "run-1",
        "shipment_id": "1000324895",
        "reference_number": "DIAMOND-RPN1",
        "tenant_settings": {"appointment_scheduling": {}},
        "llm_appointment_decision": {
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
    return SimpleNamespace(
        data=data,
        tenant_id=data.get("tenant_id"),
        execution_id=data.get("execution_id", "run-1"),
    )


def test_skipped_when_not_weekend_shifted() -> None:
    state = _state(
        llm_appointment_decision={
            "weekend_shifted": False,
            "selected_pickup_date": "2026-07-01",
            "selected_pickup_time": "08:00",
        }
    )
    result = WeekendPickupService().apply_weekend_shifted_pickup_from_state(state)
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

    result = WeekendPickupService().apply_weekend_shifted_pickup_from_state(_state())

    assert result.ok is True
    assert result.skipped is False
    assert result.ascend_updated is True
    assert result.turvo_updated is True
    assert result.turvo_pickup_start_time == "2026-07-01 08:00:00"


@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.skip_ascend_writes_enabled",
    return_value=True,
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.update_stop_appointment_time",
    new_callable=AsyncMock,
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.update_appointment",
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.login_ascend_api",
)
def test_skip_ascend_writes_still_updates_turvo(
    mock_login: MagicMock,
    mock_update_appt: MagicMock,
    mock_turvo_update: AsyncMock,
    _skip: MagicMock,
) -> None:
    mock_turvo_update.return_value = {
        "ok": True,
        "updated": True,
        "stop_name": "Pickup WH",
    }

    result = WeekendPickupService().apply_weekend_shifted_pickup_from_state(_state())

    assert result.ok is True
    assert result.skipped is False
    assert result.dry_run is True
    assert result.ascend_updated is False
    assert result.turvo_updated is True
    assert result.turvo_pickup_start_time == "2026-07-01 08:00:00"
    mock_login.assert_not_called()
    mock_update_appt.assert_not_called()
    mock_turvo_update.assert_awaited_once()


@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.skip_ascend_writes_enabled",
    return_value=True,
)
@patch(
    "app.services.appointment_scheduling.weekend_pickup_service.update_stop_appointment_time",
    new_callable=AsyncMock,
)
def test_skip_ascend_writes_turvo_failure_still_fails(
    mock_turvo_update: AsyncMock,
    _skip: MagicMock,
) -> None:
    mock_turvo_update.return_value = {"ok": False, "error": "stop_not_found"}

    result = WeekendPickupService().apply_weekend_shifted_pickup_from_state(_state())

    assert result.ok is False
    assert result.dry_run is True
    assert result.ascend_updated is False
    assert result.failure is not None
    assert "stop_not_found" in (result.error or "")
