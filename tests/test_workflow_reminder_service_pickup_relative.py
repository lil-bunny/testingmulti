"""Pickup-relative reminder scheduling tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.services.workflow_reminder_service import WorkflowReminderService


def _before_pickup_settings(*, catch_up_missed_steps: bool = True) -> dict:
    return {
        "driver_assignment": {
            "reminders": WorkflowRemindersConfig(
                schedule_mode="before_pickup",
                catch_up_missed_steps=catch_up_missed_steps,
                steps=[
                    {"step": 1, "event_type": "reminder_due", "delay_hours": 48},
                    {"step": 2, "event_type": "reminder_due", "delay_hours": 24},
                    {"step": 3, "event_type": "reminder_due", "delay_hours": 12},
                    {"step": 4, "event_type": "reminder_due", "delay_hours": 6},
                ],
                expire_grace_hours=2,
            ).model_dump()
        }
    }


def _legacy_before_pickup_settings() -> dict:
    return {
        "driver_assignment": {
            "reminders": {
                "schedule_mode": "before_pickup",
                "offsets_before_pickup_hours": [48, 24, 12, 6],
                "expire_grace_hours": 2,
            }
        }
    }


def _schedule_driver_assignment(
    data: dict,
    *,
    hours_until_pickup: float | None = None,
) -> datetime:
    anchor = datetime.now(timezone.utc)
    if hours_until_pickup is not None:
        data["pickup_appointment_at"] = (
            anchor + timedelta(hours=hours_until_pickup)
        ).isoformat()

    with (
        patch(
            "app.services.workflow_reminder_service.datetime",
            wraps=datetime,
        ) as mock_datetime,
        patch(
            "app.services.workflow_reminder_service.WorkflowLifecycleService"
        ) as mock_lifecycle_cls,
    ):
        mock_datetime.now.return_value = anchor
        mock_lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
            "sub_status": "none",
        }
        WorkflowReminderService().schedule(data, workflow_name="driver_assignment")
    return anchor


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_uses_eta(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    anchor = datetime.now(timezone.utc)
    pickup_at = anchor + timedelta(days=5)
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "shipments_row_id": "ship-row-1",
        "ratecon_workflow_lifecycle_id": "ratecon-wl-1",
        "pickup_appointment_at": pickup_at.isoformat(),
        "pickup_appointment_timezone": "America/Los_Angeles",
        "tenant_settings": _before_pickup_settings(),
    }

    _schedule_driver_assignment(data)

    assert data["reminders_scheduled"] is True
    assert mock_task.apply_async.call_count == 4
    first_call = mock_task.apply_async.call_args_list[0]
    assert "eta" in first_call.kwargs
    assert first_call.kwargs["eta"] == pickup_at - timedelta(hours=48)
    payload = first_call.kwargs["kwargs"]["payload"]
    assert payload["shipments_row_id"] == "ship-row-1"
    assert payload["ratecon_workflow_lifecycle_id"] == "ratecon-wl-1"

    schedule = data["driver_reminder_schedule"]
    assert schedule["catch_up"] is None
    assert len(schedule["reminder_steps"]) == 4
    assert schedule["skipped_steps"] == []
    assert schedule["suppressed_steps"] == []


@patch("app.services.workflow_reminder_service.WorkflowReminderCancelService")
@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_registers_queued_tasks(
    mock_task: MagicMock, mock_cancel_cls: MagicMock
) -> None:
    mock_result = MagicMock()
    mock_result.id = "celery-task-1"
    mock_task.apply_async.return_value = mock_result
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _before_pickup_settings(),
    }

    _schedule_driver_assignment(data, hours_until_pickup=10)

    mock_cancel_cls.return_value.register_tasks.assert_called_once()
    call = mock_cancel_cls.return_value.register_tasks.call_args
    assert call.kwargs["lifecycle_id"] == "wl-1"
    assert len(call.kwargs["entries"]) == 2


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_catch_up_at_r10(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _before_pickup_settings(),
    }

    _schedule_driver_assignment(data, hours_until_pickup=10)

    assert data["reminders_scheduled"] is True
    assert mock_task.apply_async.call_count == 2
    schedule = data["driver_reminder_schedule"]
    assert schedule["catch_up"]["delay_hours"] == 12
    assert len(schedule["reminder_steps"]) == 1
    assert schedule["reminder_steps"][0]["delay_hours"] == 6
    assert len(schedule["skipped_steps"]) == 2
    assert schedule["suppressed_steps"] == []


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_r25_suppresses_24(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _before_pickup_settings(),
    }

    _schedule_driver_assignment(data, hours_until_pickup=25)

    assert mock_task.apply_async.call_count == 3
    schedule = data["driver_reminder_schedule"]
    assert schedule["catch_up"]["delay_hours"] == 48
    assert len(schedule["suppressed_steps"]) == 1
    assert schedule["suppressed_steps"][0]["delay_hours"] == 24
    assert [s["delay_hours"] for s in schedule["reminder_steps"]] == [12, 6]


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_r27_schedules_all(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _before_pickup_settings(),
    }

    _schedule_driver_assignment(data, hours_until_pickup=27)

    assert mock_task.apply_async.call_count == 4
    schedule = data["driver_reminder_schedule"]
    assert schedule["catch_up"]["delay_hours"] == 48
    assert schedule["suppressed_steps"] == []
    assert [s["delay_hours"] for s in schedule["reminder_steps"]] == [24, 12, 6]


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_legacy_skip_only_when_catch_up_disabled(
    mock_task: MagicMock,
) -> None:
    mock_task.apply_async.return_value = MagicMock()
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "tenant_settings": _before_pickup_settings(catch_up_missed_steps=False),
    }

    _schedule_driver_assignment(data, hours_until_pickup=10)

    assert mock_task.apply_async.call_count == 1
    schedule = data["driver_reminder_schedule"]
    assert schedule["catch_up"] is None
    assert len(schedule["reminder_steps"]) == 1
    assert len(schedule["skipped_steps"]) == 3


@patch("app.services.workflow_reminder_service.trigger_workflow_reminder")
def test_schedule_before_pickup_legacy_offsets_normalized(mock_task: MagicMock) -> None:
    mock_task.apply_async.return_value = MagicMock()
    anchor = datetime.now(timezone.utc)
    pickup_at = anchor + timedelta(days=5)
    data = {
        "tenant_id": "tenant-1",
        "tenant_slug": "t3ra",
        "workflow_lifecycle_id": "wl-1",
        "pickup_appointment_at": pickup_at.isoformat(),
        "tenant_settings": _legacy_before_pickup_settings(),
    }

    _schedule_driver_assignment(data)

    assert data["reminders_scheduled"] is True
    assert mock_task.apply_async.call_count == 4
    first_call = mock_task.apply_async.call_args_list[0]
    assert first_call.kwargs["eta"] == pickup_at - timedelta(hours=48)
