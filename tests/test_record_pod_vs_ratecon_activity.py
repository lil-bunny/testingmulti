"""Tests for POD vs ratecon validation activity log graph node."""

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
        "documents_pod_merged": {"stored": True, "id": "doc-merged-1"},
        "pod_merged_pdf_object_key": "freightx/pod_attachments/pod_1000324895.pdf",
        "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
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
def test_record_pod_vs_ratecon_activity_validation_stored(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.workflows.nodes.record_pod_activity import record_pod_vs_ratecon_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "document_analysis_pod_vs_ratecon": {
                "stored": True,
                "id": "analysis-vs-1",
            },
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "confidence_score": 0.91,
                "overall_status": "PASS",
                "validation_summary": "All fields match.",
            },
            "communication_id": COMM_UUID,
        }
    )

    record_pod_vs_ratecon_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert (
        sequence.steps[0].description
        == "POD validated against ratecon confidence=0.91 (PASS)"
    )
    assert sequence.steps[0].metadata["validation_document_analysis_id"] == "analysis-vs-1"
    assert sequence.steps[0].metadata["overall_status"] == "PASS"
    assert sequence.steps[0].metadata["confidence_score"] == 0.91


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_vs_ratecon_activity_validation_skipped(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.workflows.nodes.record_pod_activity import record_pod_vs_ratecon_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "skipped": True,
                "reason": "ratecon_analysis_not_success",
            },
        }
    )

    record_pod_vs_ratecon_activity(state)

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert (
        sequence.steps[0].description
        == "POD vs ratecon validation skipped (ratecon_analysis_not_success)"
    )
    assert sequence.steps[0].metadata["validation_skipped"] is True
    assert sequence.steps[0].metadata["validation_skip_reason"] == "ratecon_analysis_not_success"


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_vs_ratecon_activity_validation_failed(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.workflows.nodes.record_pod_activity import record_pod_vs_ratecon_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "pod_vs_ratecon_analysis_results": {
                "success": False,
                "error": "missing_pod_data",
            },
        }
    )

    record_pod_vs_ratecon_activity(state)

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == "POD vs ratecon validation failed"
    assert sequence.steps[0].metadata["error"] == "missing_pod_data"


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_vs_ratecon_activity_skips_without_extraction(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_vs_ratecon_activity

    state = _base_state()
    state.data.pop("document_analysis_pod")

    record_pod_vs_ratecon_activity(state)
    mock_svc_cls.assert_not_called()
