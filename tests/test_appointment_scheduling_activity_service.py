"""Tests for AppointmentSchedulingActivityService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.appointment_scheduling.activity_service import (
    AppointmentSchedulingActivityService,
)

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "22222222-3333-4444-5555-666666666666"


def _state(**data_overrides):
    data = {
        "workflow_lifecycle_id": _LIFECYCLE_UUID,
        "tenant_id": _TENANT_UUID,
        "reference_number": "DIAMOND-RPN00008809",
        "customer_name": "BUCHANAN CELLERS WAREHOUSE",
        "llm_scheduling_decision": {
            "selected_pickup_date": "07/01/2026",
            "calculated_delivery_date": "07/04/2026",
            "calculated_delivery_weekday": "FRIDAY",
        },
    }
    data.update(data_overrides)
    return SimpleNamespace(
        tenant_id=_TENANT_UUID,
        execution_id=_RUN_UUID,
        data=data,
    )


def test_record_started_writes_status_change() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_started(_state())

    activity.record_sequence.assert_called_once()
    seq = activity.record_sequence.call_args[0][0]
    assert len(seq.steps) == 1
    step = seq.steps[0]
    assert step.activity_type == ActivityType.STATUS_CHANGE
    assert step.from_status == StatusType.NONE
    assert step.from_sub_status == StatusSubType.NONE
    assert step.to_status == StatusType.PROCESSING
    assert step.to_sub_status == StatusSubType.APPOINTMENT_SCHEDULING_STARTED


def test_record_started_skips_when_already_started() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_started(_state())
    svc.record_started(_state())

    activity.record_sequence.assert_not_called()


def test_record_decision_info_includes_llm_source() -> None:
    activity = MagicMock()
    svc = AppointmentSchedulingActivityService(activity_log_service=activity)

    svc.record_decision(_state())

    seq = activity.record_sequence.call_args[0][0]
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert seq.steps[0].metadata["decision_source"] == "llm"


def test_record_decision_info_uses_transit_days_for_costco() -> None:
    activity = MagicMock()
    svc = AppointmentSchedulingActivityService(activity_log_service=activity)

    svc.record_decision(
        _state(
            customer_name="COSTCO WHOLESALE",
            llm_scheduling_decision={
                "selected_pickup_date": "07/01/2026",
                "calculated_delivery_date": "07/04/2026",
                "calculated_delivery_weekday": "FRIDAY",
                "transit_days": 3,
            },
        )
    )

    seq = activity.record_sequence.call_args[0][0]
    assert seq.steps[0].metadata["decision_source"] == "transit_days"
    assert seq.steps[0].metadata["transit_days"] == 3


def test_record_draft_ready_writes_action_and_status_change() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    email_draft = {"to": "wh@example.com", "subject": "DEL APPT REQ"}
    scheduling_payload = {"reference_number": "DIAMOND-1"}

    svc.record_draft_ready(
        _state(),
        email_draft=email_draft,
        scheduling_payload=scheduling_payload,
    )

    seq = activity.record_sequence.call_args[0][0]
    assert len(seq.steps) == 2
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert seq.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert seq.steps[1].to_status == StatusType.PENDING_REVIEW
    assert seq.steps[1].to_sub_status == StatusSubType.APPOINTMENT_DRAFT_CREATED


def test_record_email_sent_minimal_metadata() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.APPOINTMENT_DRAFT_CREATED.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_email_sent(
        _state(actor_user_id="99999999-9999-9999-9999-999999999999"),
        communication_id="comm-uuid",
        actor_id="99999999-9999-9999-9999-999999999999",
    )

    seq = activity.record_sequence.call_args[0][0]
    assert len(seq.steps) == 1
    assert seq.steps[0].metadata is None
    assert seq.steps[0].communication_id == "comm-uuid"
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert seq.actor_type.value == "user"
    assert seq.actor_id == "99999999-9999-9999-9999-999999999999"


def test_finalize_confirm_awaiting_reply_writes_status_change() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.APPOINTMENT_DRAFT_CREATED.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.finalize_confirm_awaiting_reply(
        _state(actor_user_id="99999999-9999-9999-9999-999999999999"),
        communication_id="comm-uuid",
        actor_id="99999999-9999-9999-9999-999999999999",
    )

    seq = activity.record_sequence.call_args[0][0]
    assert len(seq.steps) == 1
    assert seq.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert seq.steps[0].to_sub_status == StatusSubType.AWAITING_CUSTOMER_REPLY


def test_record_failed_writes_action_and_failed_status() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_failed(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        workflow_run_id=_RUN_UUID,
        reason="missing_recipient_email",
    )

    seq = activity.record_sequence.call_args[0][0]
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert "missing_recipient_email" in (seq.steps[0].description or "")
    assert seq.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert seq.steps[1].to_status == StatusType.FAILED


def test_record_reply_completed_writes_completed_status() -> None:
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
    }
    svc = AppointmentSchedulingActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )

    svc.record_reply_completed(
        _state(
            confirmed_delivery_at="2026-07-18T10:30:00",
            customer_reply_decision="sufficient",
        )
    )

    seq = activity.record_sequence.call_args[0][0]
    assert len(seq.steps) == 2
    assert seq.steps[0].activity_type == ActivityType.ACTION
    assert seq.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert seq.steps[1].to_status == StatusType.COMPLETED
    assert seq.steps[1].to_sub_status == StatusSubType.APPOINTMENT_SCHEDULED
