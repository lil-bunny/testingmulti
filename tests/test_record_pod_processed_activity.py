"""Tests for POD processed finalize activity log graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

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


def _lifecycle_row(*, sub_status: str = "document_uploaded") -> dict:
    return {"status": "processing", "sub_status": sub_status}


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_processed_activity_sets_pending_review_on_success(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
            "document_analysis_pod_vs_ratecon": {
                "stored": True,
                "id": "analysis-vs-1",
            },
            "pod_analysis_results": {"success": True, "confidence_score": 0.82},
            "pod_vs_ratecon_analysis_results": {
                "success": True,
                "confidence_score": 0.91,
                "overall_status": "PASS",
            },
        }
    )

    record_pod_processed_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_PROCESSED
    assert sequence.steps[0].metadata["shipment_id"] == "1000324895"


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_processed_activity_analysis_failure(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "pod_analysis_results": {
                "success": False,
                "reason": "extraction_empty",
            },
        }
    )

    record_pod_processed_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.FAILED


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_processed_activity_skips_when_upload_failed(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

    state = _base_state(
        data={
            "documents_pod": None,
            "pod_merged_pdf_object_key": None,
            "attachment_normalization": {"success": False},
            "document_analysis_pod": {"stored": True, "id": "analysis-1"},
        }
    )
    state.data.pop("documents_pod", None)
    state.data.pop("pod_merged_pdf_object_key", None)

    record_pod_processed_activity(state)
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_processed_activity_idempotent_skip(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_processed"
    )

    state = _base_state(
        data={
            "document_analysis_pod": {"stored": True, "id": "analysis-1"},
        }
    )

    record_pod_processed_activity(state)
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_processed_activity_runs_after_uploaded_to_tms(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_pod_activity import record_pod_processed_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="uploaded_to_tms"
    )

    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
            "pod_analysis_results": {
                "success": True,
                "confidence_score": 0.82,
            },
            "pod_vs_ratecon_analysis_results": {
                "skipped": True,
                "reason": "no_ratecon",
            },
        }
    )

    record_pod_processed_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    from app.models.status import StatusType

    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_PROCESSED
