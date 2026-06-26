"""Tests for ``update_reminder_status`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMM_UUID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


def _reminder_sent_state(**data_overrides) -> WorkflowState:
    data = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "tender_id": TENDER_UUID,
        "tender_reminder_sent": True,
        "reminder_step": 1,
        "communication_id": COMM_UUID,
        **data_overrides,
    }
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data=data,
    )


@patch("app.workflows.nodes.update_reminder_status.ActivityLogService")
@patch("app.workflows.nodes.update_reminder_status.WorkflowLifecycleService")
def test_update_reminder_status_records_action_and_transition(
    mock_lifecycle_cls: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    from app.workflows.nodes.update_reminder_status import update_reminder_status

    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.TENDER_SENT_TO_CARRIER.value,
    }

    mock_activity = MagicMock()
    mock_activity_cls.return_value = mock_activity

    state = _reminder_sent_state()
    update_reminder_status(state)

    mock_activity.record_sequence.assert_called_once()
    sequence = mock_activity.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[1].to_sub_status == StatusSubType.REMINDER_1_SENT
    assert state.data["reminder_sub_status"] == StatusSubType.REMINDER_1_SENT.value


@patch("app.workflows.nodes.update_reminder_status.ActivityLogService")
@patch("app.workflows.nodes.update_reminder_status.WorkflowLifecycleService")
def test_update_reminder_status_audit_only_when_lifecycle_completed(
    mock_lifecycle_cls: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    from app.workflows.nodes.update_reminder_status import update_reminder_status

    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.ACCEPTED.value,
    }

    mock_activity = MagicMock()
    mock_activity_cls.return_value = mock_activity

    state = _reminder_sent_state()
    update_reminder_status(state)

    mock_activity.record_sequence.assert_called_once()
    sequence = mock_activity.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].communication_id == COMM_UUID
    assert state.data["reminder_status_skipped"] == "lifecycle_already_completed"
    assert "reminder_sub_status" not in state.data


@patch("app.workflows.nodes.update_reminder_status.ActivityLogService")
def test_update_reminder_status_skips_when_reminder_not_sent(
    mock_activity_cls: MagicMock,
) -> None:
    from app.workflows.nodes.update_reminder_status import update_reminder_status

    state = _reminder_sent_state(tender_reminder_sent=False)
    update_reminder_status(state)

    mock_activity_cls.assert_not_called()
    assert state.data["reminder_status_skipped"] == "reminder_not_sent"
