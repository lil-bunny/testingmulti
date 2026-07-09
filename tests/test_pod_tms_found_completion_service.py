"""Unit tests for PodLifecycleTmsFoundCompletionService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.pod_lifecycle.tms_found_completion_service import (
    PodLifecycleTmsFoundCompletionService,
)


def _state(**data_overrides) -> WorkflowState:
    data = {
        "event_type": "reminder_due",
        "pod_exists": True,
        "workflow_lifecycle_id": "22222222-2222-2222-2222-222222222222",
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "execution_id": "33333333-3333-3333-3333-333333333333",
        "shipments_row_id": "44444444-4444-4444-4444-444444444444",
    }
    data.update(data_overrides)
    return WorkflowState(
        tenant_id=data["tenant_id"],
        tenant_slug="t3ra",
        execution_id=data["execution_id"],
        data=data,
    )


def test_completes_with_info_and_status_change_from_processing():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
    }
    activity = MagicMock()
    cancel = MagicMock()
    cancel.cancel_all.return_value = 2

    result = PodLifecycleTmsFoundCompletionService(
        lifecycle_service=lifecycle,
        activity_log_service=activity,
        reminder_cancel_service=cancel,
    ).complete_on_reminder_from_state(_state())

    assert result.completed is True
    assert result.already_terminal is False
    assert result.reminders_cancelled == 2
    sequence = activity.record_sequence.call_args[0][0]
    assert sequence.actor_type == ActorType.SYSTEM
    assert sequence.actor_id is None
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.INFO
    assert sequence.steps[0].description == "Pod found in TMS"
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.UPLOADED_TO_TMS
    cancel.cancel_all.assert_called_once_with(
        lifecycle_id="22222222-2222-2222-2222-222222222222"
    )


def test_idempotent_when_already_terminal_skips_activity_still_cancels():
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.UPLOADED_TO_TMS.value,
    }
    activity = MagicMock()
    cancel = MagicMock()
    cancel.cancel_all.return_value = 1

    state = _state()
    result = PodLifecycleTmsFoundCompletionService(
        lifecycle_service=lifecycle,
        activity_log_service=activity,
        reminder_cancel_service=cancel,
    ).complete_on_reminder_from_state(state)

    assert result.completed is True
    assert result.already_terminal is True
    activity.record_sequence.assert_not_called()
    cancel.cancel_all.assert_called_once()
    assert state.data["pod_found_in_tms_already_terminal"] is True


@pytest.mark.parametrize(
    "overrides,reason",
    [
        ({"event_type": "route_completed"}, "not_reminder_due"),
        ({"pod_exists": False}, "pod_not_found"),
        ({"workflow_lifecycle_id": ""}, "missing_ids"),
    ],
)
def test_no_op_when_gates_fail(overrides, reason):
    lifecycle = MagicMock()
    activity = MagicMock()
    cancel = MagicMock()

    result = PodLifecycleTmsFoundCompletionService(
        lifecycle_service=lifecycle,
        activity_log_service=activity,
        reminder_cancel_service=cancel,
    ).complete_on_reminder_from_state(_state(**overrides))

    assert result.completed is False
    assert result.skip_reason == reason
    activity.record_sequence.assert_not_called()
    cancel.cancel_all.assert_not_called()
