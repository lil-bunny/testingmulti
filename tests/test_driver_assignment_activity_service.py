"""DriverAssignmentActivityService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.driver_assignment_activity_service import DriverAssignmentActivityService


def _state(**data_overrides):
    data = {
        "workflow_lifecycle_id": "driver-lc-1",
        "tenant_id": "tenant-1",
        "shipment_id": "1000324895",
        "shipments_row_id": "row-1",
        "load_id": "load-1",
        "ratecon_workflow_lifecycle_id": "ratecon-lc-1",
        "pickup_appointment_at": "2026-03-30T15:30:00+00:00",
        "pickup_appointment_timezone": "America/Los_Angeles",
        "reminders_scheduled": True,
        "driver_reminder_schedule": {
            "pickup_appointment_at": "2026-03-30T15:30:00+00:00",
            "pickup_appointment_timezone": "America/Los_Angeles",
            "reminder_steps": [
                {"step": 1, "offset_hours": 48.0, "fire_at": "2026-03-28T15:30:00+00:00"}
            ],
            "skipped_steps": [],
        },
    }
    data.update(data_overrides)
    return SimpleNamespace(
        tenant_id=data.get("tenant_id"),
        execution_id="run-1",
        data=data,
    )


def test_record_started_skips_without_reminders_scheduled():
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)
    state = _state(reminders_scheduled=False)

    svc.record_started(state)

    activity.record_sequence.assert_not_called()


def test_record_started_writes_action_and_status():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_started(_state())

    sequence = activity.record_sequence.call_args.args[0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PROCESSING


def test_record_reminders_scheduled_includes_fire_at_metadata():
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)

    svc.record_reminders_scheduled(_state())

    sequence = activity.record_sequence.call_args.args[0]
    meta = sequence.steps[0].metadata
    assert meta["reminder_steps"][0]["fire_at"] == "2026-03-28T15:30:00+00:00"
    assert meta["pickup_appointment_at"] == "2026-03-30T15:30:00+00:00"


def test_record_not_started_on_ratecon_action_only():
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)

    svc.record_not_started_on_ratecon(
        tenant_id="tenant-1",
        ratecon_workflow_lifecycle_id="ratecon-lc-1",
        workflow_run_id="ratecon-run-1",
        skip_reason="pickup_appointment_not_found",
        shipment_id="1000324895",
        load_id="load-1",
        shipments_row_id="row-1",
    )

    sequence = activity.record_sequence.call_args.args[0]
    assert len(sequence.steps) == 1
    assert sequence.workflow_lifecycle_id == "ratecon-lc-1"
    assert "pickup_appointment_not_found" in sequence.steps[0].description
