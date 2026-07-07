"""Tests for ``log_tender_activity`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
COMM_UUID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


@patch("app.workflows.nodes.log_tender_activity.ActivityLogService")
def test_log_tender_activity_success_uses_record_sequence(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType
    from app.workflows.nodes.log_tender_activity import log_tender_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tender_email_sent": True,
            "communication_id": COMM_UUID,
        },
    )

    log_tender_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.workflow_run_id == RUN_UUID
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.SUB_STATUS_CHANGE
    assert sequence.steps[0].description == "Tender email sent to Shipper"
    assert sequence.steps[1].description is None
    assert sequence.steps[1].to_status is None
    assert sequence.steps[1].to_sub_status == StatusSubType.TENDER_SENT_TO_TENANT
    assert sequence.steps[0].communication_id == COMM_UUID
    assert sequence.steps[0].metadata is None
    assert sequence.steps[1].communication_id is None
    assert sequence.steps[1].metadata is None


@patch("app.workflows.nodes.log_tender_activity.ActivityLogService")
def test_log_tender_activity_failure_uses_status_change_only(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.status import StatusType
    from app.workflows.nodes.log_tender_activity import log_tender_activity

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tender_email_sent": False,
            "tender_email_error": "unipile_down",
        },
    )

    log_tender_activity(state)

    mock_svc.record_sequence.assert_not_called()
    mock_svc.record_status_change.assert_called_once()
    write = mock_svc.record_status_change.call_args[0][0]
    assert write.to_status == StatusType.FAILED
    assert write.workflow_run_id == RUN_UUID


@patch("app.workflows.nodes.log_tender_activity.ActivityLogService")
def test_log_tender_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.log_tender_activity import log_tender_activity

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={"tender_email_sent": True},
    )

    log_tender_activity(state)
    mock_svc_cls.assert_not_called()
