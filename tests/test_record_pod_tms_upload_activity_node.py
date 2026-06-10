"""Workflow node tests for record_pod_tms_upload_activity."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.workflows.nodes.record_pod_tms_upload_activity import (
    record_pod_tms_upload_activity,
)


def test_record_pod_tms_upload_activity_node_uploaded():
    state = SimpleNamespace(
        execution_id="run-1",
        data={
            "workflow_lifecycle_id": "wl-1",
            "tenant_id": "tenant-1",
            "shipment_id": "1000324895",
            "shipments_row_id": "ship-1",
            "turvo_upload_result": {
                "success": True,
                "document": {"id": "tms-doc-1"},
            },
        },
    )

    with patch(
        "app.workflows.nodes.record_pod_tms_upload_activity.WorkflowLifecycleService"
    ) as lifecycle_cls, patch(
        "app.workflows.nodes.record_pod_tms_upload_activity.record_pod_tms_upload_activity_fn",
        return_value=True,
    ) as record_fn:
        lifecycle_cls.return_value.read_lifecycle_row_by_id.return_value = {
            "status": "processing",
            "sub_status": "pod_started",
        }
        record_pod_tms_upload_activity(state)

    record_fn.assert_called_once()
    assert record_fn.call_args.kwargs["outcome"] == "uploaded"
    assert state.data["pod_tms_upload_activity_recorded"] is True
    assert state.data["pod_tms_upload_outcome"] == "uploaded"


def test_record_pod_tms_upload_activity_node_skips_without_ids():
    state = SimpleNamespace(execution_id="", data={})
    record_pod_tms_upload_activity(state)
    assert state.data["pod_tms_upload_activity_recorded"] is False
