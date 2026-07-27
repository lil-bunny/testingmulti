"""Tests for PodPipelineActivityService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.state import WorkflowState
from app.services.pod_lifecycle.pipeline_activity_service import PodPipelineActivityService

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


def test_extraction_metadata_id_only() -> None:
    from app.models.activity_type import ActivityType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodPipelineActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "document_analysis_pod": {"stored": True, "id": "analysis-pod-1"},
            "pod_analysis_results": {
                "success": True,
                "confidence_score": 0.82,
                "pod_status": "UNKNOWN",
            },
        }
    )

    service.record_extraction_from_state(state)

    sequence = mock_activity.record_sequence.call_args[0][0]
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].metadata == {"document_analysis_id": "analysis-pod-1"}


def test_started_status_metadata_none() -> None:
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.NONE.value,
        "sub_status": StatusSubType.NONE.value,
    }

    service = PodPipelineActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    service.record_started_from_state(_base_state(data={"reminders_scheduled": True}))

    step = mock_activity.record_sequence.call_args[0][0].steps[0]
    assert step.metadata is None


def test_reminder_transition_metadata_none_action_has_step() -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": StatusSubType.POD_STARTED.value,
    }

    service = PodPipelineActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    service.record_reminder_from_state(
        _base_state(
            data={
                "pod_reminder_sent": True,
                "reminder_step": 1,
                "communication_id": COMM_UUID,
            }
        )
    )

    sequence = mock_activity.record_sequence.call_args[0][0]
    assert sequence.steps[0].metadata == {"reminder_step": 1}
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].metadata is None
