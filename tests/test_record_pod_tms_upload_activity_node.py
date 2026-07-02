"""Workflow node tests for record_pod_tms_upload_activity (thin delegate)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.workflows.nodes.record_pod_tms_upload_activity import record_pod_tms_upload_activity


@patch("app.workflows.nodes.record_pod_tms_upload_activity.record_pod_tms_upload_from_state")
def test_record_pod_tms_upload_activity_node_delegates(mock_from_state) -> None:
    mock_from_state.return_value = "uploaded"
    state = SimpleNamespace(
        execution_id="run-1",
        data={"workflow_lifecycle_id": "wl-1"},
    )

    result = record_pod_tms_upload_activity(state)

    mock_from_state.assert_called_once_with(state)
    assert result is state
