"""Tests for pod_lifecycle activity log graph nodes."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
COMM_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _base_state(*, data: dict | None = None) -> WorkflowState:
    payload = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "shipment_id": "1000324895",
        "thread_id": "thread-1",
    }
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data=payload,
    )


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_started_activity_calls_record_sequence(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_started_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
    }
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_pod_started_activity(
        _base_state(data={"reminders_scheduled": True})
    )

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.tenant_id == TENANT_UUID
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PROCESSING
    assert sequence.steps[0].to_sub_status == StatusSubType.POD_STARTED


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_started_activity_skips_without_reminders_scheduled(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_started_activity

    record_pod_started_activity(_base_state())
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_started_activity_skips_when_already_started(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_started_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
    }

    record_pod_started_activity(
        _base_state(data={"reminders_scheduled": True})
    )
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_reminder_activity_step1_status_change(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_reminder_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
    }
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_pod_reminder_activity(
        _base_state(
            data={
                "pod_reminder_sent": True,
                "reminder_step": 1,
                "communication_id": COMM_UUID,
            }
        )
    )

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_1_SENT


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_reminder_activity_step2_sub_status_change(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_reminder_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_pod_reminder_activity(
        _base_state(data={"pod_reminder_sent": True, "reminder_step": 2})
    )

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_2_SENT


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_reminder_activity_step3_sub_status_change(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_reminder_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_2_SENT.value,
    }
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_pod_reminder_activity(
        _base_state(data={"pod_reminder_sent": True, "reminder_step": 3})
    )

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_3_SENT


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_reminder_activity_skips_when_not_sent(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_reminder_activity

    record_pod_reminder_activity(
        _base_state(data={"pod_reminder_sent": False, "reminder_step": 1})
    )
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_escalation_activity_sub_status_change(
    mock_svc_cls: MagicMock,
    mock_wl_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_pod_activity import record_pod_escalation_activity

    mock_wl_cls.return_value.read_lifecycle_row_by_id.return_value = {
        "status": "pending_review",
        "sub_status": StatusSubType.REMINDER_3_SENT.value,
    }
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_pod_escalation_activity(_base_state())

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_sub_status == StatusSubType.ESCALATED
    assert sequence.steps[1].from_sub_status == StatusSubType.REMINDER_3_SENT


@patch("app.workflows.nodes.email.stash_communication_id")
@patch("app.workflows.nodes.email.send_email_tool")
def test_send_email_sets_pod_reminder_sent_and_communication_id(
    mock_send: MagicMock,
    mock_stash: MagicMock,
) -> None:
    from app.workflows.nodes.email import send_email

    mock_send.return_value = {
        "success": True,
        "communication_id": COMM_UUID,
    }

    state = _base_state(
        data={
            "to": "carrier@example.com",
            "tenant_settings": {
                "mikey_account_id": "acc-from-tenant",
            },
        }
    )
    send_email(state)

    assert state.data["pod_reminder_sent"] is True
    mock_stash.assert_called_once()
    mock_send.assert_called_once()
    assert mock_send.call_args.kwargs.get("account_id") == "acc-from-tenant"
    assert mock_send.call_args.kwargs.get("workflow_run_id") == RUN_UUID
