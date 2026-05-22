"""Tests for ``record_tender_calc_failure`` helper."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch("app.workflows.nodes.gelita.load_tendering_helpers.LifecycleTransitionService")
def test_record_tender_calc_failure_applies_transition(
    mock_transition_cls: MagicMock,
) -> None:
    from app.workflows.nodes.gelita.load_tendering_helpers import record_tender_calc_failure

    mock_svc = MagicMock()
    mock_transition_cls.return_value = mock_svc

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

    mock_svc.apply.assert_called_once()
    command = mock_svc.apply.call_args[0][0]
    assert command.to_status == StatusType.FAILED
    assert command.activity_type == ActivityType.STATUS_CHANGE
    assert command.metadata["error"] == "missing_pack_code"
    assert command.metadata["pack_code"] == "9999"
