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
    assert sequence.steps[1].to_sub_status == StatusSubType.DRIVER_ASSIGNMENT_STARTED


def _reminder_state(**data_overrides):
    base = {
        "driver_reminder_sent": True,
        "tenant_settings": {
            "driver_assignment": {
                "reminders": {
                    "schedule_mode": "before_pickup",
                    "offsets_before_pickup_hours": [48, 24, 12, 6],
                }
            }
        },
    }
    base.update(data_overrides)
    if "reminder_step" not in base:
        base["reminder_step"] = 1
    return _state(**base)


def test_record_reminder_sent_skips_when_not_sent():
    activity = MagicMock()
    lifecycle = MagicMock()
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_state(driver_reminder_sent=False, reminder_step=1))

    activity.record_sequence.assert_not_called()
    lifecycle.read_lifecycle_row_by_id.assert_not_called()


def test_record_reminder_sent_step1_status_change_to_pending_review():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_reminder_state(reminder_step=1))

    sequence = activity.record_sequence.call_args.args[0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_1_SENT


def test_record_reminder_sent_step2_sub_status_change_only():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_reminder_state(reminder_step=2))

    sequence = activity.record_sequence.call_args.args[0]
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_2_SENT
    assert sequence.steps[1].to_status is None


def test_record_reminder_sent_step4_sub_status():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_3_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_reminder_state(reminder_step=4))

    sequence = activity.record_sequence.call_args.args[0]
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_4_SENT


def test_record_reminder_sent_links_communication_id():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.DRIVER_ASSIGNMENT_STARTED.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_reminder_state(reminder_step=1, communication_id="comm-1"))

    sequence = activity.record_sequence.call_args.args[0]
    assert sequence.steps[0].communication_id == "comm-1"
    assert sequence.steps[1].communication_id is None


def test_record_reminder_sent_skips_when_lifecycle_completed():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.REMINDER_4_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(_reminder_state(reminder_step=1))

    activity.record_sequence.assert_not_called()

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
