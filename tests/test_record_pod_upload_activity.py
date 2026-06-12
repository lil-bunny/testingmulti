"""Tests for POD S3 upload activity log graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.models.activity_type import ActorType

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


def _lifecycle_row(*, sub_status: str = "reminder_3_sent") -> dict:
    return {"status": "pending_review", "sub_status": sub_status}


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_success_merged_doc(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "documents_pod_merged": {
                "stored": True,
                "id": "doc-merged-1",
            },
            "pod_merged_pdf_object_key": "freightx/pod_attachments/pod_1000324895.pdf",
        }
    )

    record_pod_upload_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == "POD document uploaded to S3"
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_sub_status == StatusSubType.DOCUMENT_UPLOADED
    assert sequence.steps[0].metadata["object_key"] == (
        "freightx/pod_attachments/pod_1000324895.pdf"
    )


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_manual_user_actor(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "uploaded_by_user_id": "user-42",
            "manual_pod_document_id": "doc-manual-1",
            "pod_object_keys": ["freightx/pod_attachments/pod_manual.pdf"],
        }
    )

    record_pod_upload_activity(state)

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.actor_type == ActorType.USER
    assert sequence.actor_id == "user-42"


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_failure(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusType
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row()

    state = _base_state(
        data={
            "attachment_normalization": {
                "success": False,
                "error": "PDF merge failed",
            }
        }
    )

    record_pod_upload_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.FAILED


@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data={
            "documents_pod_merged": {"stored": True, "id": "doc-1"},
        },
    )
    record_pod_upload_activity(state)
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_idempotent_skip(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="document_uploaded"
    )

    state = _base_state(
        data={
            "documents_pod_merged": {"stored": True, "id": "doc-1"},
        }
    )

    record_pod_upload_activity(state)
    mock_svc_cls.assert_not_called()


@patch("app.workflows.nodes.record_pod_activity.WorkflowLifecycleService")
@patch("app.workflows.nodes.record_pod_activity.ActivityLogService")
def test_record_pod_upload_activity_runs_after_uploaded_to_tms(
    mock_svc_cls: MagicMock,
    mock_lc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType
    from app.workflows.nodes.record_pod_activity import record_pod_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc
    mock_lc_cls.return_value.read_lifecycle_row_by_id.return_value = _lifecycle_row(
        sub_status="uploaded_to_tms"
    )

    state = _base_state(
        data={
            "event_type": "manual_pod_upload",
            "documents_pod_merged": {"stored": True, "id": "doc-merged-1"},
            "pod_merged_pdf_object_key": "freightx/pod_attachments/pod_1000324895.pdf",
        }
    )

    record_pod_upload_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == "POD document uploaded to S3"
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[1].to_sub_status == StatusSubType.DOCUMENT_UPLOADED
    assert sequence.steps[1].from_sub_status == StatusSubType.UPLOADED_TO_TMS
