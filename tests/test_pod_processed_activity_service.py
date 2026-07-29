"""Tests for PodProcessedActivityService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.state import WorkflowState
from app.models.status import StatusSubType, StatusType
from app.services.pod_lifecycle.processed_activity_service import PodProcessedActivityService

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


def _lifecycle_row(*, sub_status: str = "document_uploaded", status: str = "processing") -> dict:
    return {"status": status, "sub_status": sub_status}


def test_manual_success_moves_to_pending_review() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
        }
    )

    service.record_from_state(state)
    mock_activity.record_sequence.assert_called_once()


def test_manual_stop_mismatch_moves_to_pending_review() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()
    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
            "pod_scoring_results": {
                "success": True,
                "score": {"needs_action": True, "review_reasons": ["PO A mismatched pickup"]},
            },
        }
    )

    service.record_from_state(state)

    mock_activity.record_sequence.assert_called_once()
    sequence = mock_activity.record_sequence.call_args[0][0]
    assert sequence.steps[0].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_PROCESSED


def test_email_success_sets_pending_review() -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "email_received",
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
        }
    )

    service.record_from_state(state)

    mock_activity.record_sequence.assert_called_once()
    sequence = mock_activity.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 1
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PENDING_REVIEW
    assert sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_PROCESSED
    assert sequence.steps[0].metadata is None


def test_manual_analysis_failure_skips() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "pod_analysis_results": {"success": False, "reason": "extraction_empty"},
        }
    )

    service.record_from_state(state)
    mock_activity.record_sequence.assert_not_called()


def test_email_analysis_failure_marks_failed() -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "email_received",
            "pod_analysis_results": {"success": False, "reason": "extraction_empty"},
        }
    )

    service.record_from_state(state)

    sequence = mock_activity.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].to_status == StatusType.FAILED


def test_manual_fresh_reupload_records_review_transition_when_already_processed() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_processed"
    )

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "manual_pod_upload_source": "upload",
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
        }
    )

    service.record_from_state(state)
    mock_activity.record_sequence.assert_called_once()


def test_email_idempotent_skip_when_already_processed() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_processed"
    )

    service = PodProcessedActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "email_received",
            "document_analysis_pod": {"stored": True, "id": "analysis-1"},
        }
    )

    service.record_from_state(state)
    mock_activity.record_sequence.assert_not_called()
