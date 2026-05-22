"""Tests for ``record_tender_created_activity`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch(
    "app.workflows.nodes.gelita.record_tender_created_activity.LifecycleTransitionService"
)
@patch("app.workflows.nodes.gelita.record_tender_created_activity.ActivityLogService")
def test_record_tender_created_activity_calls_both_logs(
    mock_activity_svc_cls: MagicMock,
    mock_transition_svc_cls: MagicMock,
) -> None:
    from app.models.activity_type import ActivityType
    from app.models.status import StatusSubType, StatusType
    from app.workflows.nodes.gelita.record_tender_created_activity import (
        record_tender_created_activity,
    )

    mock_activity_svc = MagicMock()
    mock_activity_svc_cls.return_value = mock_activity_svc
    mock_transition_svc = MagicMock()
    mock_transition_svc_cls.return_value = mock_transition_svc

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

    mock_activity_svc.record_tender_created_action.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        order_number="ORD-1",
        customer_name="Acme Corp",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )
    mock_transition_svc.apply.assert_called_once()
    command = mock_transition_svc.apply.call_args[0][0]
    assert command.activity_type == ActivityType.STATUS_CHANGE
    assert command.to_status == StatusType.PROCESSING
    assert command.to_sub_status == StatusSubType.TENDER_CREATED


@patch("app.workflows.nodes.gelita.record_tender_created_activity.ActivityLogService")
def test_record_tender_created_activity_skips_when_ids_missing(
    mock_svc_cls: MagicMock,
) -> None:
    from app.workflows.nodes.gelita.record_tender_created_activity import (
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
