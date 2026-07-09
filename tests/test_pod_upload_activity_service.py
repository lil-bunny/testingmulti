"""Tests for PodUploadActivityService."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.domain.state import WorkflowState
from app.services.pod_lifecycle.upload_activity_service import PodUploadActivityService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
COMM_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


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


def _lifecycle_row(*, sub_status: str = "reminder_3_sent", status: str = "pending_review") -> dict:
    return {"status": status, "sub_status": sub_status}


def test_manual_success_info_user_then_system_pipeline() -> None:
    from app.models.activity_type import ActivityType, ActorType
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "uploaded_by_user_id": "user-42",
            "pod_object_keys": ["pod_attachments/pod_manual.pdf"],
        }
    )

    service.record_from_state(state)

    assert mock_activity.record_sequence.call_count == 2
    info_sequence = mock_activity.record_sequence.call_args_list[0][0][0]
    pipeline_sequence = mock_activity.record_sequence.call_args_list[1][0][0]

    assert info_sequence.actor_type == ActorType.USER
    assert info_sequence.actor_id == "user-42"
    assert len(info_sequence.steps) == 1
    assert info_sequence.steps[0].activity_type == ActivityType.INFO
    assert info_sequence.steps[0].description == "POD uploaded manually"
    assert info_sequence.steps[0].metadata is None

    assert pipeline_sequence.actor_type == ActorType.SYSTEM
    assert len(pipeline_sequence.steps) == 2
    assert pipeline_sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert pipeline_sequence.steps[0].to_status == StatusType.PROCESSING
    assert pipeline_sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_UPLOADED
    assert pipeline_sequence.steps[0].metadata is None
    assert pipeline_sequence.steps[1].activity_type == ActivityType.ACTION
    assert pipeline_sequence.steps[1].description == "POD document uploaded to S3"
    assert pipeline_sequence.steps[1].communication_id is None


def test_email_success_two_steps_with_comms_on_action() -> None:
    from app.models.activity_type import ActivityType, ActorType
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "email_received",
            "documents_pod": {
                "stored": True,
                "id": "doc-merged-1",
                "metadata": {
                    "source_object_keys": ["pod_attachments/pod_1000324895.pdf"],
                },
            },
            "pod_merged_pdf_object_key": "pod_attachments/pod_1000324895.pdf",
            "communication_id": COMM_UUID,
        }
    )

    service.record_from_state(state)

    sequence = mock_activity.record_sequence.call_args[0][0]
    assert sequence.actor_type == ActorType.SYSTEM
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[0].to_status == StatusType.PROCESSING
    assert sequence.steps[1].communication_id == COMM_UUID
    assert sequence.steps[1].metadata["object_key"] == "pod_attachments/pod_1000324895.pdf"
    assert sequence.steps[0].metadata is None


def test_upload_failure_marks_failed() -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "attachment_normalization": {
                "success": False,
                "error": "PDF merge failed",
            }
        }
    )

    service.record_from_state(state)

    sequence = mock_activity.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].to_status == StatusType.FAILED


def test_idempotent_skip_email() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_uploaded"
    )

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "email_received",
            "documents_pod": {"stored": True, "id": "doc-1"},
        }
    )

    service.record_from_state(state)
    mock_activity.record_sequence.assert_not_called()


def test_manual_fresh_reupload_from_pending_review() -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType

    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "pending_review",
        "sub_status": "document_processed",
    }

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "manual_pod_upload_source": "upload",
            "documents_pod": {"stored": True, "id": "doc-1"},
            "pod_merged_pdf_object_key": "pod_attachments/pod_reupload.pdf",
        }
    )

    service.record_from_state(state)

    assert mock_activity.record_sequence.call_count == 2
    pipeline_sequence = mock_activity.record_sequence.call_args_list[1][0][0]
    assert pipeline_sequence.steps[0].activity_type == ActivityType.STATUS_CHANGE
    assert pipeline_sequence.steps[0].to_status == StatusType.PROCESSING
    assert pipeline_sequence.steps[0].to_sub_status == StatusSubType.DOCUMENT_UPLOADED


def test_manual_fresh_reupload_bypasses_idempotent_skip() -> None:
    mock_activity = MagicMock()
    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_uploaded"
    )

    service = PodUploadActivityService(
        activity_log_service=mock_activity,
        lifecycle_service=mock_lifecycle,
    )
    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "manual_pod_upload_source": "upload",
            "documents_pod": {"stored": True, "id": "doc-1"},
            "pod_merged_pdf_object_key": "pod_attachments/pod_reupload.pdf",
        }
    )

    service.record_from_state(state)
    assert mock_activity.record_sequence.call_count == 2
