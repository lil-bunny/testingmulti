"""DriverAssignmentCancelService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.workflow_cancel_trigger import (
    RATECON_SUPERSEDED_TRIGGER,
    SHIPMENT_TENDERED_TRIGGER,
    WorkflowCancelTrigger,
)
from app.services.driver_assignment.cancel_service import DriverAssignmentCancelService
from app.services.workflow_lifecycle_cancel_service import WorkflowCancelResult

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_SHIPMENTS_ROW_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LC_ID = "driver-lc-active"


def _trigger(**overrides) -> WorkflowCancelTrigger:
    base = {
        "trigger": SHIPMENT_TENDERED_TRIGGER,
        "tenant_id": _TENANT_ID,
        "tenant_slug": "t3ra",
        "shipment_number": "1000324895",
        "load_id": "30389",
        "metadata": {"vendor": "turvo", "turvo_status_key": "2101"},
    }
    base.update(overrides)
    return WorkflowCancelTrigger(**base)


def _service(**kwargs) -> DriverAssignmentCancelService:
    cancel = kwargs.get("cancel_service") or MagicMock()
    shipments = kwargs.get("shipments_service") or MagicMock()
    return DriverAssignmentCancelService(
        cancel_service=cancel,
        shipments_service=shipments,
    )


def test_cancel_for_trigger_delegates_to_shared_cancel() -> None:
    cancel = MagicMock()
    cancel.cancel_by_shipment.return_value = WorkflowCancelResult(
        cancelled=True,
        lifecycle_id=_LC_ID,
    )
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_ID}
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(_trigger())

    assert result.cancelled is True
    assert result.lifecycle_id == _LC_ID
    cancel.cancel_by_shipment.assert_called_once()
    meta = cancel.cancel_by_shipment.call_args.kwargs["metadata"]
    assert meta["vendor"] == "turvo"
    assert meta["turvo_status_key"] == "2101"


def test_cancel_for_trigger_maps_not_found_to_no_active_lifecycle() -> None:
    cancel = MagicMock()
    cancel.cancel_by_shipment.return_value = WorkflowCancelResult(
        cancelled=False,
        skip_reason="not_found",
    )
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_ID}
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(_trigger())

    assert result.cancelled is False
    assert result.skip_reason == "no_active_lifecycle"


def test_cancel_for_trigger_uses_shipments_row_id_when_set() -> None:
    cancel = MagicMock()
    cancel.cancel_by_shipment.return_value = WorkflowCancelResult(
        cancelled=True,
        lifecycle_id=_LC_ID,
    )
    shipments = MagicMock()
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(
            _trigger(shipment_number=None, shipments_row_id=_SHIPMENTS_ROW_ID)
        )

    assert result.cancelled is True
    shipments.get_by_shipment_number.assert_not_called()
    assert cancel.cancel_by_shipment.call_args.kwargs["shipment_row_id"] == _SHIPMENTS_ROW_ID


def test_cancel_for_trigger_no_shipment() -> None:
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = None
    svc = _service(shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(_trigger())

    assert result.skip_reason == "shipment_not_found"


def test_cancel_for_trigger_missing_correlation() -> None:
    svc = _service()
    result = svc.cancel_for_trigger(
        _trigger(shipment_number=None, shipments_row_id=None)
    )
    assert result.skip_reason == "missing_shipment_correlation"


def test_cancel_for_trigger_success_terminal_skip() -> None:
    cancel = MagicMock()
    cancel.cancel_by_shipment.return_value = WorkflowCancelResult(
        cancelled=False,
        lifecycle_id=_LC_ID,
        skip_reason="success_terminal",
    )
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_ID}
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(_trigger())

    assert result.cancelled is False
    assert result.skip_reason == "success_terminal"


def test_cancel_for_trigger_ratecon_superseded_uses_supersede_path() -> None:
    cancel = MagicMock()
    cancel.supersede_by_shipment.return_value = WorkflowCancelResult(
        cancelled=True,
        lifecycle_id=_LC_ID,
    )
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_ID}
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(
            _trigger(trigger=RATECON_SUPERSEDED_TRIGGER, metadata={"load_id": "30389"})
        )

    assert result.cancelled is True
    cancel.supersede_by_shipment.assert_called_once()
    cancel.cancel_by_shipment.assert_not_called()
    shipments.clear_driver_details.assert_called_once_with(
        tenant_id=_TENANT_ID,
        shipment_row_id=_SHIPMENTS_ROW_ID,
    )


def test_cancel_for_trigger_ratecon_supersede_skips_clear_when_not_cancelled() -> None:
    cancel = MagicMock()
    cancel.supersede_by_shipment.return_value = WorkflowCancelResult(
        cancelled=False,
        skip_reason="not_found",
    )
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_ID}
    svc = _service(cancel_service=cancel, shipments_service=shipments)

    with patch(
        "app.services.driver_assignment.cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_for_trigger(
            _trigger(trigger=RATECON_SUPERSEDED_TRIGGER, shipments_row_id=_SHIPMENTS_ROW_ID)
        )

    assert result.skip_reason == "no_active_lifecycle"
    shipments.clear_driver_details.assert_not_called()
