"""Tests for notify_pod_analysis_teams graph node (thin delegate)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.services.pod_lifecycle.teams_notification_service import PodTeamsNotificationResult
from app.workflows.nodes.record_pod_activity import notify_pod_analysis_teams


@patch("app.workflows.nodes.record_pod_activity.PodLifecycleTeamsNotificationService")
def test_notify_pod_analysis_teams_delegates_to_service(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_svc.notify_from_state.return_value = PodTeamsNotificationResult(
        sent=True,
        skip_reason=None,
        error=None,
    )
    state = WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={"event_type": "email_received", "load_id": "30389"},
    )

    result = notify_pod_analysis_teams(state)

    mock_svc_cls.assert_called_once_with()
    mock_svc.notify_from_state.assert_called_once_with(state)
    assert result is state
    assert state.data["pod_teams_notification_sent"] is True
