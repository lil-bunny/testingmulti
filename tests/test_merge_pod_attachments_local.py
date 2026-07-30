"""Tests for in-graph merge_pod_attachments_local node."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.error_catalog import BusinessError
from app.domain.state import WorkflowState
from app.services.pod_lifecycle.attachment_pipeline_service import (
    PodAttachmentPipelineResult,
)
from app.workflows.nodes.pod import merge_pod_attachments_local


def test_merge_local_node_success_patches_state():
    state = WorkflowState(
        tenant_id="t1",
        tenant_slug="t3ra",
        execution_id="e1",
        data={
            "shipment_id": "SHIP",
            "pod_merge_source_paths": ["/tmp/a.pdf"],
            "pod_attachment_stage_dir": "/tmp/stage",
        },
    )
    with patch(
        "app.services.pod_lifecycle.attachment_pipeline_service.PodAttachmentPipelineService.merge_local_from_state",
        return_value=PodAttachmentPipelineResult(
            success=True,
            state_patch={
                "pod_merged_local_path": "/tmp/stage/pod_SHIP.pdf",
            },
        ),
    ):
        out = merge_pod_attachments_local(state)

    assert out.data["pod_merged_local_path"] == "/tmp/stage/pod_SHIP.pdf"
    assert "error" not in out.data


def test_merge_local_node_failure_sets_business_error(tmp_path):
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "x.pdf").write_bytes(b"%PDF")
    state = WorkflowState(
        tenant_id="t1",
        tenant_slug="t3ra",
        execution_id="e1",
        data={
            "shipment_id": "SHIP",
            "pod_merge_source_paths": [str(stage / "x.pdf")],
            "pod_attachment_stage_dir": str(stage),
        },
    )
    with patch(
        "app.services.pod_lifecycle.attachment_pipeline_service.PodAttachmentPipelineService.merge_local_from_state",
        return_value=PodAttachmentPipelineResult(
            success=False,
            skip_reason="attachment_normalization_failed",
        ),
    ):
        out = merge_pod_attachments_local(state)

    assert out["data"]["error"]["code"] == BusinessError.POD_ATTACHMENT_UPLOAD_FAILED.value
    assert not stage.exists()
