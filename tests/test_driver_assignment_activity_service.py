"""DriverAssignmentActivityService unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.driver_assignment.activity_service import DriverAssignmentActivityService


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
                {"step": 1, "delay_hours": 48.0, "fire_at": "2026-03-28T15:30:00+00:00"}
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


def test_record_started_writes_status_only():
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
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PROCESSING
    assert sequence.steps[0].to_sub_status == StatusSubType.DRIVER_ASSIGNMENT_STARTED


def _reminder_state(**data_overrides):
    base = {
        "driver_reminder_sent": True,
        "tenant_settings": {
            "driver_assignment": {
                "reminders": {
                    "schedule_mode": "before_pickup",
                    "steps": [
                        {"step": 1, "event_type": "reminder_due", "delay_hours": 48},
                        {"step": 2, "event_type": "reminder_due", "delay_hours": 24},
                        {"step": 3, "event_type": "reminder_due", "delay_hours": 12},
                        {"step": 4, "event_type": "reminder_due", "delay_hours": 6},
                    ],
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


def test_record_reminder_sent_step2_stays_pending_review():
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
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_2_SENT


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
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
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


def test_record_reminder_sent_partial_follow_up_action_template():
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

    svc.record_reminder_sent(
        _reminder_state(reminder_step=2, driver_reminder_is_partial_follow_up=True)
    )

    sequence = activity.record_sequence.call_args.args[0]
    assert "partial follow-up" in sequence.steps[0].description.lower()
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_2_SENT


def test_record_tms_driver_success_logs_single_assign_action():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    state = _state(
        tms_resolution="found",
        tms_contact_id=123,
        tms_search_match_by="phone",
        tms_driver_outcome="assigned",
        driver_details_decision="has_details",
        driver_details_extraction={
            "decision": "has_details",
            "driver": {"name": "John Doe", "phone": "555-0100", "email": None},
        },
    )

    svc.record_tms_driver_success(state)

    sequence = activity.record_sequence.call_args.args[0]
    action_steps = [
        step for step in sequence.steps if step.activity_type == ActivityType.ACTION
    ]
    sub_statuses = [
        step.to_sub_status
        for step in sequence.steps
        if step.activity_type == ActivityType.SUB_STATUS_CHANGE
    ]
    assert len(action_steps) == 1
    assert "assigned to shipment in tms" in action_steps[0].description.lower()
    assert sub_statuses == [StatusSubType.UPLOADED_TO_TMS]
    transition_steps = [
        step
        for step in sequence.steps
        if step.activity_type == ActivityType.SUB_STATUS_CHANGE
    ]
    assert all(step.to_status == StatusType.PENDING_REVIEW for step in transition_steps)
    assert state.data["driver_details_recorded"] is True


def test_record_tms_driver_success_created_logs_single_assign_action():
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
    state = _state(
        tms_resolution="created",
        tms_contact_id=640861,
        tms_contact_created=True,
        tms_search_match_by="name_and_phone",
        tms_driver_outcome="assigned",
        driver_details_extraction={
            "driver": {"name": "Lily Potter", "phone": "+19832487248"},
        },
    )

    svc.record_tms_driver_success(state)

    sequence = activity.record_sequence.call_args.args[0]
    action_steps = [
        step for step in sequence.steps if step.activity_type == ActivityType.ACTION
    ]
    assert len(action_steps) == 1
    assert "assigned to shipment in tms" in action_steps[0].description.lower()
    assert action_steps[0].metadata["tms_resolution"] == "created"
    assert action_steps[0].metadata["tms_contact_created"] is True


def test_record_tms_driver_success_insufficient_still_logs_assign():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    state = _state(
        communication_id="inbound-comm-1",
        tms_resolution="found",
        tms_contact_id=123,
        tms_search_match_by="name",
        tms_driver_outcome="assigned",
        driver_details_decision="insufficient",
        driver_details_extraction={
            "decision": "insufficient",
            "driver": {"name": "Emily Sharma", "phone": None, "email": None},
        },
    )

    svc.record_tms_driver_success(state)

    sequence = activity.record_sequence.call_args.args[0]
    action_steps = [
        step for step in sequence.steps if step.activity_type == ActivityType.ACTION
    ]
    sub_statuses = [
        step.to_sub_status
        for step in sequence.steps
        if step.activity_type == ActivityType.SUB_STATUS_CHANGE
    ]
    assert len(action_steps) == 1
    assert "assigned to shipment in tms" in action_steps[0].description.lower()
    assert sub_statuses == [StatusSubType.UPLOADED_TO_TMS]
    assert all(step.communication_id is None for step in sequence.steps)


def test_record_tms_driver_success_from_processing_no_pending_review():
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
    state = _state(
        tms_resolution="found",
        tms_contact_id=123,
        tms_search_match_by="phone",
        tms_driver_outcome="assigned",
        driver_details_decision="has_details",
        driver_details_extraction={
            "decision": "has_details",
            "driver": {"name": "John Doe", "phone": "555-0100", "email": None},
        },
    )

    svc.record_tms_driver_success(state)

    sequence = activity.record_sequence.call_args.args[0]
    transition_steps = [
        step
        for step in sequence.steps
        if step.activity_type == ActivityType.SUB_STATUS_CHANGE
    ]
    assert transition_steps
    assert all(
        step.to_status != StatusType.PENDING_REVIEW for step in transition_steps
    )
    assert all(step.to_status == StatusType.PROCESSING for step in transition_steps)
    assert [step.to_sub_status for step in transition_steps] == [
        StatusSubType.UPLOADED_TO_TMS,
    ]


def test_record_reminder_sent_partial_follow_up_at_cap_action_only():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_4_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reminder_sent(
        _reminder_state(
            reminder_step=4,
            driver_reminder_is_partial_follow_up=True,
            driver_reminder_skip_sub_status_bump=True,
        )
    )

    sequence = activity.record_sequence.call_args.args[0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert "partial follow-up" in sequence.steps[0].description.lower()
    assert sequence.steps[0].metadata.get("ladder_at_cap") is True


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


def test_record_tms_driver_not_resolved_uses_tms_metadata_keys():
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)
    state = _state(
        tms_resolution="not_found",
        tms_search_match_by="phone",
        tms_match_count=0,
        tms_carrier_id=848297,
        communication_id="inbound-comm-1",
        driver_details_extraction={"driver": {"name": None, "phone": "+1454235353"}},
    )
    svc.record_tms_driver_not_resolved(state)
    sequence = activity.record_sequence.call_args.args[0]
    meta = sequence.steps[0].metadata
    assert meta["tms_resolution"] == "not_found"
    assert meta["tms_search_match_by"] == "phone"
    assert "turvo_" not in "".join(meta.keys())
    assert "not found in TMS" in sequence.steps[0].description
    assert sequence.steps[0].communication_id is None


def test_record_tms_driver_success_skipped_already_assigned_completes():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    svc.record_tms_driver_success(
        _state(
            tms_resolution="skipped_already_assigned",
            tms_driver_outcome="assigned",
        )
    )
    sequence = activity.record_sequence.call_args.args[0]
    uploaded_step = next(
        step
        for step in sequence.steps
        if step.to_sub_status == StatusSubType.UPLOADED_TO_TMS
        and step.activity_type == ActivityType.SUB_STATUS_CHANGE
    )
    assert uploaded_step.to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[-1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[-1].to_status == StatusType.COMPLETED
    assert sequence.steps[-1].to_sub_status == StatusSubType.UPLOADED_TO_TMS


def test_record_driver_assignment_completed_after_confirmation():
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.UPLOADED_TO_TMS.value,
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    svc.record_driver_details_confirmation_sent(
        _state(
            driver_confirmation_sent=True,
            tms_is_tracking_customer=False,
            driver_details_extraction={"driver": {"name": "anna", "phone": "555"}},
        )
    )
    confirm_seq = activity.record_sequence.call_args.args[0]
    assert "Driver confirmation email sent" in confirm_seq.steps[0].description

    svc.record_driver_assignment_completed(
        _state(
            driver_confirmation_sent=True,
            tms_is_tracking_customer=False,
        )
    )
    complete_seq = activity.record_sequence.call_args.args[0]
    assert complete_seq.steps[0].to_status == StatusType.COMPLETED


def test_record_driver_assignment_completed_skips_without_confirmation():
    activity = MagicMock()
    svc = DriverAssignmentActivityService(activity_log_service=activity)
    svc.record_driver_assignment_completed(_state(driver_confirmation_sent=False))
    activity.record_sequence.assert_not_called()
