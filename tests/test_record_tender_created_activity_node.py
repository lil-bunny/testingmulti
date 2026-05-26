"""Tests for ``record_tender_created_activity`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch("app.workflows.nodes.record_tender_created_activity.ActivityLogService")
def test_record_tender_created_activity_calls_record_sequence(
    mock_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.record_tender_created_activity import (
        record_tender_created_activity,
    )

    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "tender_row": {
                "order_number": "ORD-1",
                "customer_name": "Acme Corp",
            },
        },
    )

    record_tender_created_activity(state)

    mock_svc.record_sequence.assert_called_once()
    sequence = mock_svc.record_sequence.call_args[0][0]
    assert sequence.tenant_id == TENANT_UUID
    assert len(sequence.steps) == 2
    assert sequence.steps[0].activity_type == ActivityType.ACTION
    assert sequence.steps[1].activity_type == ActivityType.STATUS_CHANGE
    assert sequence.steps[1].to_status == StatusType.PROCESSING
    assert sequence.steps[1].to_sub_status == StatusSubType.TENDER_CREATED


@patch("app.workflows.nodes.record_tender_created_activity.ActivityLogService")
def test_record_tender_created_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.record_tender_created_activity import (
        record_tender_created_activity,
    )

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={},
    )

    record_tender_created_activity(state)
    mock_svc_cls.assert_not_called()
