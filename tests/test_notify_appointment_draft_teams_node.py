"""Tests for notify_appointment_draft_teams graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.workflows.nodes.appointment_scheduling.nodes import notify_appointment_draft_teams


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.LifecycleService"
)
def test_notify_appointment_draft_teams_delegates_to_lifecycle_service(
    mock_lifecycle_cls: MagicMock,
) -> None:
    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    state = WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={"event_type": "turvo_pickup_changed", "load_id": "62396"},
    )

    result = notify_appointment_draft_teams(state)

    mock_lifecycle_cls.assert_called_once_with()
    mock_lifecycle.finalize_after_teams_notify.assert_called_once_with(state)
    assert result is state


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.LifecycleService"
)
def test_notify_node_delegates_skip_path_to_lifecycle_service(
    mock_lifecycle_cls: MagicMock,
) -> None:
    mock_lifecycle = MagicMock()
    mock_lifecycle_cls.return_value = mock_lifecycle
    state = WorkflowState(tenant_id="t1", tenant_slug="t3ra", execution_id="r1", data={})

    notify_appointment_draft_teams(state)

    mock_lifecycle.finalize_after_teams_notify.assert_called_once_with(state)
