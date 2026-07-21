"""Tests for notify_appointment_scheduling_draft_teams graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.services.appointment_scheduling.teams_notification_service import (
    AppointmentSchedulingTeamsNotificationResult,
)
from app.workflows.nodes.appointment_scheduling.nodes import (
    notify_appointment_scheduling_draft_teams,
)


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTeamsNotificationService"
)
def test_notify_appointment_scheduling_draft_teams_delegates_to_service(
    mock_svc_cls: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.notify_from_state.return_value = AppointmentSchedulingTeamsNotificationResult(
        sent=True,
        skip_reason=None,
        error=None,
    )
    state = WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={"event_type": "turvo_pickup_changed", "load_id": "62396"},
    )

    result = notify_appointment_scheduling_draft_teams(state)

    mock_svc_cls.assert_called_once_with()
    mock_svc.notify_from_state.assert_called_once_with(state)
    assert result is state
    assert state.data["appointment_scheduling_teams_notification_sent"] is True


@patch(
    "app.workflows.nodes.appointment_scheduling.nodes.AppointmentSchedulingTeamsNotificationService"
)
def test_notify_node_stashes_skip_and_error_flags(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.notify_from_state.return_value = AppointmentSchedulingTeamsNotificationResult(
        skipped=True,
        skip_reason="no_teams_notification_settings",
        error=None,
    )
    state = WorkflowState(tenant_id="t1", tenant_slug="t3ra", execution_id="r1", data={})

    notify_appointment_scheduling_draft_teams(state)

    assert state.data["appointment_scheduling_teams_notification_skipped"] == (
        "no_teams_notification_settings"
    )
