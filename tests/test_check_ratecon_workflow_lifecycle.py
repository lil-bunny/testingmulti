"""Unit tests for ``check_ratecon_workflow_lifecycle`` graph node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.workflows.nodes.workflow_lifecycle import check_ratecon_workflow_lifecycle

_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LIFECYCLE_ID = "11111111-2222-3333-4444-555555555555"
_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_EXEC_UUID = "22222222-3333-4444-5555-666666666666"


def test_check_ratecon_uses_shipment_uuid_not_load_id() -> None:
    state = WorkflowState(
        tenant_id=_TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=_EXEC_UUID,
        data={
            "tenant_id": _TENANT_UUID,
            "load_id": "56368",
            "shipment_id": "SHIP-99",
            "shipments_row_id": _ROW_UUID,
            "thread_id": "thread-abc",
        },
    )
    svc = MagicMock()
    svc.resolve_shipments_row_id.return_value = _ROW_UUID
    svc.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _LIFECYCLE_ID,
    }

    with patch(
        "app.workflows.nodes.workflow_lifecycle.WorkflowLifecycleService",
        return_value=svc,
    ):
        out = check_ratecon_workflow_lifecycle(state)

    svc.check_lifecycle_exists.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_name="ratecon",
        shipment_id=_ROW_UUID,
    )
    result = out.data["ratecon_workflow_lifecycle"]
    assert result["in_workflow_lifecycle"] is True
    assert result["lifecycle_id"] == _LIFECYCLE_ID
    assert result["shipments_row_id"] == _ROW_UUID


def test_check_ratecon_missing_shipments_row_id() -> None:
    state = WorkflowState(
        tenant_id=_TENANT_UUID,
        tenant_slug="t3ra",
        execution_id=_EXEC_UUID,
        data={
            "tenant_id": _TENANT_UUID,
            "load_id": "56368",
            "shipment_id": "SHIP-99",
        },
    )
    svc = MagicMock()
    svc.resolve_shipments_row_id.return_value = None

    with patch(
        "app.workflows.nodes.workflow_lifecycle.WorkflowLifecycleService",
        return_value=svc,
    ):
        out = check_ratecon_workflow_lifecycle(state)

    svc.check_lifecycle_exists.assert_not_called()
    result = out.data["ratecon_workflow_lifecycle"]
    assert result["in_workflow_lifecycle"] is False
    assert result["message"] == "missing_shipments_row_id"
