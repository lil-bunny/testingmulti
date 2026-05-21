"""Tests for ``record_tender_calc_failure`` helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.models.status import StatusType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch("app.workflows.nodes.gelita.load_tendering_helpers.ActivityLogService")
@patch("app.workflows.nodes.gelita.load_tendering_helpers.WorkflowLifecycleService")
def test_record_tender_calc_failure_updates_status_only(
    mock_lifecycle_cls: MagicMock,
    mock_activity_cls: MagicMock,
) -> None:
    from app.workflows.nodes.gelita.load_tendering_helpers import record_tender_calc_failure

    mock_lifecycle = MagicMock()
    mock_lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PROCESSING.value,
        "sub_status": "tender_created",
    }
    mock_lifecycle_cls.return_value = mock_lifecycle
    mock_activity = MagicMock()
    mock_activity_cls.return_value = mock_activity

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "tender_id": TENDER_UUID,
            "pack_code": "9999",
        },
    )

    record_tender_calc_failure(state, error_code="missing_pack_code")

    mock_lifecycle.update_lifecycle_status.assert_called_once_with(
        lifecycle_id=LIFECYCLE_UUID,
        status=StatusType.FAILED,
    )
    mock_activity.record_activity.assert_called_once()
    kwargs = mock_activity.record_activity.call_args.kwargs
    assert kwargs["to_status"] == StatusType.FAILED
    assert "from_sub_status" not in kwargs
    assert "to_sub_status" not in kwargs
    assert kwargs["metadata"]["error"] == "missing_pack_code"
    assert kwargs["metadata"]["pack_code"] == "9999"
