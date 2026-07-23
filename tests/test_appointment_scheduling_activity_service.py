"""Tests for ActivityService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_RUN_UUID = "22222222-3333-4444-5555-666666666666"
_COMM_UUID = "33333333-3333-4444-5555-666666666667"


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


def _svc(*, transitions=None, lifecycle=None, activity_log=None):
    return ActivityService(
        transition_service=transitions,
        lifecycle_service=lifecycle,
        activity_log_service=activity_log,
    )


def test_record_started_writes_status_change() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_started(_state())

    transitions.apply.assert_called_once()
    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.STATUS_CHANGE
    assert cmd.from_status == StatusType.NONE
    assert cmd.from_sub_status == StatusSubType.NONE
    assert cmd.to_status == StatusType.PROCESSING
    assert cmd.to_sub_status == StatusSubType.APPOINTMENT_SCHEDULING_STARTED


def test_record_started_skips_when_already_started() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_started(_state())

    transitions.apply.assert_not_called()


def test_record_decision_info_includes_llm_source() -> None:
    transitions = MagicMock()
    svc = _svc(transitions=transitions)

    svc.record_decision(_state())

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.ACTION
    assert cmd.metadata is None
    assert "source=llm" in (cmd.description or "")


def test_record_decision_info_costco_uses_llm_source() -> None:
    transitions = MagicMock()
    svc = _svc(transitions=transitions)

    svc.record_decision(
        _state(
            customer_name="COSTCO WHOLESALE",
            llm_scheduling_decision={
                "selected_pickup_date": "07/01/2026",
                "calculated_delivery_date": "07/03/2026",
                "calculated_delivery_weekday": "FRIDAY",
                "transit_days": 2,
            },
        )
    )

    cmd = transitions.apply.call_args[0][0]
    assert cmd.metadata is None
    assert "source=llm" in (cmd.description or "")


def test_record_draft_ready_writes_action_only() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    svc = _svc(transitions=transitions, lifecycle=lifecycle)
    email_draft = {"to": "wh@example.com", "subject": "DEL APPT REQ"}
    scheduling_payload = {"reference_number": "DIAMOND-1"}

    svc.record_draft_ready(
        _state(),
        email_draft=email_draft,
        scheduling_payload=scheduling_payload,
    )

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.ACTION
    assert cmd.metadata is None
    assert cmd.update_lifecycle is False
    lifecycle.read_lifecycle_row_by_id.assert_not_called()


def test_record_draft_pending_review_writes_status_change() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_draft_pending_review(_state())

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.STATUS_CHANGE
    assert cmd.to_status == StatusType.PENDING_REVIEW
    assert cmd.to_sub_status == StatusSubType.APPOINTMENT_DRAFT_CREATED


def test_record_draft_teams_notification_writes_action_only() -> None:
    transitions = MagicMock()
    svc = _svc(transitions=transitions)

    svc.record_draft_teams_notification(_state())

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.ACTION
    assert cmd.description == "Sent notification on Teams"


def test_record_confirm_email_sent_writes_user_action_with_communication() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.APPOINTMENT_DRAFT_CREATED.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_confirm_email_sent(
        _state(actor_user_id="99999999-9999-9999-9999-999999999999"),
        communication_id=_COMM_UUID,
        actor_id="99999999-9999-9999-9999-999999999999",
    )

    transitions.apply.assert_called_once()
    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.ACTION
    assert cmd.communication_id == _COMM_UUID
    assert cmd.actor_type == ActorType.USER
    assert cmd.actor_id == "99999999-9999-9999-9999-999999999999"


def test_record_awaiting_customer_reply_writes_system_sub_status_change() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.APPOINTMENT_DRAFT_CREATED.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_awaiting_customer_reply(_state())

    transitions.apply.assert_called_once()
    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.SUB_STATUS_CHANGE
    assert cmd.to_sub_status == StatusSubType.AWAITING_CUSTOMER_REPLY


def test_record_awaiting_customer_reply_skips_when_already_awaiting() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_awaiting_customer_reply(_state())

    transitions.apply.assert_not_called()


def test_record_confirm_email_sent_skips_when_already_awaiting() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_confirm_email_sent(
        _state(),
        communication_id=_COMM_UUID,
        actor_id="99999999-9999-9999-9999-999999999999",
    )

    transitions.apply.assert_not_called()


def test_record_failed_writes_exception_and_pending_review_status() -> None:
    from app.domain.appointment_scheduling.failure import SchedulingFailure
    from app.domain.error_catalog import BusinessError, format_error_message

    transitions = MagicMock()
    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.APPOINTMENT_SCHEDULING_STARTED.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle, activity_log=activity)
    failure = SchedulingFailure.from_catalog(
        BusinessError.MISSING_RECIPIENT_EMAIL,
        format_error_message(BusinessError.MISSING_RECIPIENT_EMAIL, customer_name="Acme"),
    )

    svc.record_failed(
        tenant_id=_TENANT_UUID,
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        workflow_run_id=_RUN_UUID,
        failure=failure,
    )

    exception_write = activity.record_exception.call_args[0][0]
    assert exception_write.metadata["error"] == BusinessError.MISSING_RECIPIENT_EMAIL.value
    assert exception_write.metadata["error_category"] == BusinessError.CATEGORY.value
    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.STATUS_CHANGE
    assert cmd.to_status == StatusType.PENDING_REVIEW


def test_record_reply_completed_writes_completed_status() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_reply_completed(
        _state(
            confirmed_delivery_at="2026-07-18T10:30:00",
            customer_reply_decision="accepted",
        )
    )

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.STATUS_CHANGE
    assert cmd.metadata is None
    assert cmd.to_status == StatusType.COMPLETED
    assert cmd.to_sub_status == StatusSubType.APPOINTMENT_SCHEDULED


def test_record_reply_rejected_writes_completed_rejected() -> None:
    transitions = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
    }
    svc = _svc(transitions=transitions, lifecycle=lifecycle)

    svc.record_reply_rejected(
        _state(
            customer_reply_reason="counter-proposal",
            customer_reply_decision="rejected",
        )
    )

    cmd = transitions.apply.call_args[0][0]
    assert cmd.activity_type == ActivityType.STATUS_CHANGE
    assert cmd.metadata is None
    assert cmd.to_status == StatusType.COMPLETED
    assert cmd.to_sub_status == StatusSubType.REJECTED
