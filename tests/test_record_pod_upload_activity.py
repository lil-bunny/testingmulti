"""Tests for POD S3 upload activity log graph node (thin delegate)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _base_state(*, data: dict | None = None) -> WorkflowState:
    payload = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "shipment_id": "1000324895",
        "shipments_row_id": "ship-row-1",
    }
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data=payload,
    )


@patch("app.workflows.nodes.record_pod_activity.PodUploadActivityService")
def test_record_pod_upload_activity_delegates_to_service(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    state = _base_state(data={"event_type": "manual_pod_upload"})

    result = record_pod_upload_activity(state)

    mock_svc_cls.assert_called_once_with()
    mock_svc.record_from_state.assert_called_once_with(state)
    assert result is state
