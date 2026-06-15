"""Tests for POD LLM extraction activity log graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
COMM_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


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


def _lifecycle_row(*, sub_status: str = "document_uploaded") -> dict:
    return {"status": "processing", "sub_status": sub_status}


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_extraction_activity_success(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.workflows.nodes.record_pod_activity import record_pod_extraction_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
            "pod_analysis_results": {
                "success": True,
                "confidence_score": 0.82,
                "pod_status": "UNKNOWN",
            },
            "communication_id": COMM_UUID,
        }
    )

    record_pod_extraction_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert (
        sequence.steps[0].description
        == "POD document processed — LLM extraction confidence=0.82"
    )
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[0].metadata["document_analysis_id"] == "analysis-pod-1"
    assert sequence.steps[0].metadata["extraction_confidence"] == 0.82
    assert sequence.steps[0].metadata["pod_status"] == "UNKNOWN"


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_extraction_activity_skips_when_analysis_not_stored(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_extraction_activity

    state = _base_state(
        data={
            "pod_analysis_results": {
                "success": False,
                "reason": "extraction_empty",
            },
        }
    )

    record_pod_extraction_activity(state)
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_extraction_activity_idempotent_skip(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_extraction_activity

    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_processed"
    )

    state = _base_state(
        data={
            "document_analysis_pod": {"stored": True, "id": "analysis-1"},
        }
    )

    record_pod_extraction_activity(state)
    mock_svc_cls.assert_not_called()
