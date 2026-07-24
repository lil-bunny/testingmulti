"""Workflow node tests for complete_pod_found_in_tms (thin delegate)."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.state import WorkflowState
from app.services.pod_lifecycle.tms_found_completion_service import PodTmsFoundCompletionResult
from app.workflows.nodes.pod_request import complete_pod_found_in_tms


@patch(
    "app.workflows.nodes.pod_request.PodLifecycleTmsFoundCompletionService"
)
def test_complete_pod_found_in_tms_node_delegates(mock_service_cls) -> None:
    mock_service_cls.return_value.complete_on_reminder_from_state.return_value = (
        PodTmsFoundCompletionResult(completed=True, reminders_cancelled=1)
    )
    state = WorkflowState(
        tenant_id="t",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={"event_type": "reminder_due", "pod_exists": True},
    )

    result = complete_pod_found_in_tms(state)

    assert result is state
    mock_service_cls.return_value.complete_on_reminder_from_state.assert_called_once_with(
        state
    )
