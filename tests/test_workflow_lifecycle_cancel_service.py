"""WorkflowLifecycleCancelService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.configs.workflow_cancellation_policies import DRIVER_ASSIGNMENT_CANCEL_POLICY
from app.models.status import StatusSubType, StatusType
from app.services.workflow_lifecycle_cancel_service import WorkflowLifecycleCancelService

_TENANT_ID = "550e8400-e29b-41d4-a716-446655440000"
_SHIPMENTS_ROW_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LC_ID = "driver-lc-active"


def _service(**kwargs) -> WorkflowLifecycleCancelService:
    lifecycle = kwargs.get("lifecycle_service") or MagicMock()
    activity = kwargs.get("activity_service") or MagicMock()
    return WorkflowLifecycleCancelService(
        lifecycle_service=lifecycle,
        activity_service=activity,
    )


def test_cancel_by_shipment_pending_review_reminder() -> None:
    lifecycle = MagicMock()
    lifecycle.find_in_progress_lifecycle_id.return_value = _LC_ID
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.REMINDER_1_SENT.value,
    }
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            description="Driver assignment cancelled — shipment tendered in Turvo",
            metadata={"turvo_status_key": "2101"},
        )

    assert result.cancelled is True
    assert result.lifecycle_id == _LC_ID
    activity.record_sequence.assert_called_once()
    sequence = activity.record_sequence.call_args.args[0]
    assert len(sequence.steps) == 2
    assert sequence.steps[1].to_status == StatusType.COMPLETED
    assert sequence.steps[1].to_sub_status == StatusSubType.CANCELLED


def test_cancel_by_shipment_not_found() -> None:
    lifecycle = MagicMock()
    lifecycle.find_in_progress_lifecycle_id.return_value = None
    svc = _service(lifecycle_service=lifecycle)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            description="cancelled",
            metadata={},
        )

    assert result.cancelled is False
    assert result.skip_reason == "not_found"


def test_cancel_by_shipment_success_terminal() -> None:
    lifecycle = MagicMock()
    lifecycle.find_in_progress_lifecycle_id.return_value = _LC_ID
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.PENDING_REVIEW.value,
        "sub_status": StatusSubType.UPLOADED_TO_TMS.value,
    }
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            description="cancelled",
            metadata={},
        )

    assert result.cancelled is False
    assert result.skip_reason == "success_terminal"
    activity.record_sequence.assert_not_called()


def test_cancel_by_shipment_already_cancelled_idempotent() -> None:
    lifecycle = MagicMock()
    lifecycle.find_in_progress_lifecycle_id.return_value = _LC_ID
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.CANCELLED.value,
    }
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.cancel_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            description="cancelled",
            metadata={},
        )

    assert result.cancelled is False
    assert result.skip_reason == "already_cancelled"
    activity.record_sequence.assert_not_called()


def test_supersede_by_shipment_completed_document_processed() -> None:
    from app.configs.workflow_cancellation_policies import RATECON_SUPERSEDE_POLICY

    lifecycle = MagicMock()
    lifecycle.find_latest_non_cancelled_lifecycle_id.return_value = "ratecon-lc-1"
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.DOCUMENT_PROCESSED.value,
    }
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.supersede_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=RATECON_SUPERSEDE_POLICY,
            description="Ratecon cancelled — superseded by new inbound ratecon email",
            metadata={"load_id": "30389"},
        )

    assert result.cancelled is True
    assert result.lifecycle_id == "ratecon-lc-1"
    activity.record_sequence.assert_called_once()


def test_supersede_by_shipment_completed_uploaded_to_tms_da_policy() -> None:
    from app.configs.workflow_cancellation_policies import (
        DRIVER_ASSIGNMENT_RATECON_SUPERSEDE_POLICY,
    )

    lifecycle = MagicMock()
    lifecycle.find_latest_non_cancelled_lifecycle_id.return_value = "da-lc-1"
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": StatusType.COMPLETED.value,
        "sub_status": StatusSubType.UPLOADED_TO_TMS.value,
    }
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.supersede_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=DRIVER_ASSIGNMENT_RATECON_SUPERSEDE_POLICY,
            description="Driver assignment cancelled — superseded by new inbound ratecon email",
            metadata={"load_id": "30389"},
        )

    assert result.cancelled is True
    assert result.lifecycle_id == "da-lc-1"
    activity.record_sequence.assert_called_once()


def test_supersede_by_shipment_not_found() -> None:
    from app.configs.workflow_cancellation_policies import RATECON_SUPERSEDE_POLICY

    lifecycle = MagicMock()
    lifecycle.find_latest_non_cancelled_lifecycle_id.return_value = None
    activity = MagicMock()
    svc = _service(lifecycle_service=lifecycle, activity_service=activity)

    with patch(
        "app.services.workflow_lifecycle_cancel_service.resolve_graph_tenant_to_uuid",
        return_value=_TENANT_ID,
    ):
        result = svc.supersede_by_shipment(
            tenant_id=_TENANT_ID,
            shipment_row_id=_SHIPMENTS_ROW_ID,
            policy=RATECON_SUPERSEDE_POLICY,
            description="superseded",
            metadata={},
        )

    assert result.cancelled is False
    assert result.skip_reason == "not_found"
    activity.record_sequence.assert_not_called()
