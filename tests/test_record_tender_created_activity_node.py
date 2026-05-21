"""Tests for ``record_tender_created_activity`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch("app.workflows.nodes.gelita.record_tender_created_activity.ActivityLogService")
def test_record_tender_created_activity_calls_both_logs(mock_svc_cls: MagicMock) -> None:
    from app.workflows.nodes.gelita.record_tender_created_activity import (
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

    mock_svc.record_tender_created_action.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        order_number="ORD-1",
        customer_name="Acme Corp",
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )
    mock_svc.record_tender_processing_status_change.assert_called_once_with(
        tenant_id=TENANT_UUID,
        tender_id=TENDER_UUID,
        workflow_lifecycle_id=LIFECYCLE_UUID,
        workflow_run_id=RUN_UUID,
    )


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
