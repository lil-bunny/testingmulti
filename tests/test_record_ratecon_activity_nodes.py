"""Tests for ratecon activity log graph nodes."""

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
        "load_id": "30389",
        "thread_id": "thread-1",
        "shipment_id": "1000324895",
        "shipments_row_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    }
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data=payload,
    )


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_received_activity_includes_communication_id(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_ratecon_activity import (
        record_ratecon_received_activity,
    )

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_ratecon_received_activity(_base_state(data={"communication_id": COMM_UUID}))

    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[1].communication_id == COMM_UUID


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_received_activity_calls_record_sequence(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_ratecon_activity import (
        record_ratecon_received_activity,
    )

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    record_ratecon_received_activity(_base_state())

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.tenant_id == TENANT_UUID
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PROCESSING
    assert sequence.steps[1].to_sub_status == StatusSubType.RATECON_STARTED


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_received_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_ratecon_activity import (
        record_ratecon_received_activity,
    )

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data={},
    )
    record_ratecon_received_activity(state)
    mock_svc_cls.return_value.record_sequence.assert_not_called()


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_upload_activity_success(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_ratecon_activity import record_ratecon_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _base_state(
        data={
            "ratecon_s3_upload": {
                "all_succeeded": True,
                "results": [
                    {
                        "success": True,
                        "object_key": "ratecon_attachments/ratecon_SHIP-99.pdf",
                        "document_persist": {"stored": True, "id": "doc-1"},
                    }
                ],
            },
            "communication_id": COMM_UUID,
        }
    )

    record_ratecon_upload_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[0].description == "Ratecon document uploaded to S3"
    assert sequence.steps[0].metadata["object_key"] == "ratecon_attachments/ratecon_SHIP-99.pdf"
    assert sequence.steps[0].metadata["document_id"] == "doc-1"
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.DOCUMENT_UPLOADED
    assert sequence.steps[1].from_status == StatusType.PROCESSING
    assert sequence.steps[1].from_sub_status == StatusSubType.RATECON_STARTED
    assert sequence.steps[1].communication_id == COMM_UUID


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_upload_activity_failure(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_ratecon_activity import record_ratecon_upload_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _base_state(data={"ratecon_s3_upload": {"skipped": True, "reason": "missing_email_id"}})

    record_ratecon_upload_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.EXCEPTION
    assert sequence.steps[0].description == "Ratecon document upload failed"
    assert sequence.steps[0].metadata["reason"] == "missing_email_id"
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.RATECON_STARTED
    assert sequence.steps[1].from_sub_status == StatusSubType.RATECON_STARTED


@patch("app.services.ratecon_activity_service.ActivityLogService")
def test_record_ratecon_upload_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_ratecon_activity import record_ratecon_upload_activity

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=RUN_UUID,
        data={"ratecon_s3_upload": {"skipped": True, "reason": "missing_email_id"}},
    )
    record_ratecon_upload_activity(state)
    mock_svc_cls.return_value.record_sequence.assert_not_called()
