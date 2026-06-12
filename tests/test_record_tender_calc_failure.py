"""Tests for ``record_workflow_failure_node`` global failure sink."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, workflow_error_payload
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_node_applies_transition(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_transition_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "workflow_name": "load_tendering",
            "tender_id": TENDER_UUID,
            "pack_code": "9999",
            "error": workflow_error_payload(
                code=BusinessError.MISSING_PACK_CODE.value,
                message=BusinessError.MISSING_PACK_CODE.description,
                category=BusinessError.CATEGORY,
            ),
        },
    )

    record_workflow_failure_node(state)

    mock_svc.apply_from_state.assert_called_once()
    kwargs = mock_svc.apply_from_state.call_args.kwargs
    assert kwargs["to_status"] == StatusType.PENDING_REVIEW
    assert kwargs["activity_type"] == ActivityType.STATUS_CHANGE
    assert kwargs["metadata"]["error"] == BusinessError.MISSING_PACK_CODE
    assert kwargs["metadata"]["error_category"] == BusinessError.CATEGORY.value
    assert (
        kwargs["metadata"]["error_description"]
        == BusinessError.MISSING_PACK_CODE.description
    )
    assert kwargs["metadata"]["tender_id"] == TENDER_UUID
    assert kwargs["metadata"]["pack_code"] == "9999"
    mock_enqueue.assert_called_once_with(state)


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_node_skips_enqueue_on_transition_error(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_svc.apply_from_state.side_effect = RuntimeError("db down")
    mock_transition_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "workflow_name": "load_tendering",
            "error": workflow_error_payload(
                code=BusinessError.MISSING_PACK_CODE.value,
                message=BusinessError.MISSING_PACK_CODE.description,
                category=BusinessError.CATEGORY,
            ),
        },
    )

    record_workflow_failure_node(state)

    mock_enqueue.assert_not_called()


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_node_missing_delivery_address(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_transition_cls.return_value = mock_svc

    state = WorkflowState(
        tenant_id=TENANT_UUID,
        tenant_slug="gelita",
        execution_id=RUN_UUID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_UUID,
            "workflow_name": "load_tendering",
            "tender_id": TENDER_UUID,
            "delivery_address_code": "41000100",
            "error": workflow_error_payload(
                code=BusinessError.MISSING_DELIVERY_ADDRESS.value,
                message=BusinessError.MISSING_DELIVERY_ADDRESS.description,
                category=BusinessError.CATEGORY,
            ),
        },
    )

    record_workflow_failure_node(state)

    mock_svc.apply_from_state.assert_called_once()
    kwargs = mock_svc.apply_from_state.call_args.kwargs
    assert kwargs["metadata"]["error"] == BusinessError.MISSING_DELIVERY_ADDRESS
    assert (
        kwargs["metadata"]["error_description"]
        == BusinessError.MISSING_DELIVERY_ADDRESS.description
    )
    assert kwargs["metadata"]["delivery_address_code"] == "41000100"
    mock_enqueue.assert_called_once_with(state)
