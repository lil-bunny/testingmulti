"""Tests for POD processed finalize activity log graph node (thin delegate)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _base_state(*, data: dict | None = None) -> WorkflowState:
    payload = {
        "workflow_lifecycle_id": LIFECYCLE_UUID,
        "shipment_id": "1000324895",
        "shipments_row_id": "ship-row-1",
        "documents_pod": {"stored": True, "id": "doc-merged-1"},
        "pod_merged_pdf_object_key": "pod_attachments/pod_1000324895.pdf",
    }
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data=payload,
    )


@patch("app.workflows.nodes.record_pod_activity.PodProcessedActivityService")
def test_record_pod_processed_activity_delegates_to_service(mock_svc_cls: MagicMock) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    state = _base_state(data={"event_type": "email_received"})

    result = record_pod_processed_activity(state)

    mock_svc_cls.assert_called_once_with()
    mock_svc.record_from_state.assert_called_once_with(state)
    assert result is state
