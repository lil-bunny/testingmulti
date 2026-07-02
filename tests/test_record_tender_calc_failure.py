"""Tests for ``record_workflow_failure_node`` global failure sink."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, format_error_message, workflow_error_payload
from app.domain.lifecycle_transition import LifecycleTransitionSequenceResult
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.models.status import StatusType

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TENDER_UUID = "dddddddd-dddd-dddd-dddd-dddddddddddd"
EXCEPTION_ACTIVITY_LOG_UUID = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"


PACK_MSG = format_error_message(BusinessError.MISSING_PACK_CODE, pack_code="9999")
DEL_MSG = format_error_message(
    BusinessError.MISSING_DELIVERY_ADDRESS, del_code="41000100"
)


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_node_applies_transition(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_svc.apply_sequence.return_value = LifecycleTransitionSequenceResult(
        activity_log_ids=[EXCEPTION_ACTIVITY_LOG_UUID, "status-log-id"],
        lifecycle_updated=True,
    )
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
                message=PACK_MSG,
                category=BusinessError.CATEGORY,
            ),
        },
    )

    record_workflow_failure_node(state)

    commands = mock_svc.apply_sequence.call_args[0]
    assert len(commands) == 2
    assert commands[0].activity_type == ActivityType.EXCEPTION
    assert commands[1].activity_type == ActivityType.STATUS_CHANGE
    assert commands[1].to_status == StatusType.PENDING_REVIEW
    metadata = commands[0].metadata
    assert metadata["error"] == BusinessError.MISSING_PACK_CODE.value
    assert metadata["error_category"] == BusinessError.CATEGORY.value
    assert metadata["error_description"] == PACK_MSG
    assert commands[0].description == PACK_MSG
    mock_enqueue.assert_called_once_with(
        state,
        exception_activity_log_id=EXCEPTION_ACTIVITY_LOG_UUID,
    )


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_node_skips_enqueue_on_transition_error(
    mock_transition_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    from app.workflows.nodes.error_handler import record_workflow_failure_node

    mock_svc = MagicMock()
    mock_svc.apply_sequence.side_effect = RuntimeError("db down")
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
                message=PACK_MSG,
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
    mock_svc.apply_sequence.return_value = LifecycleTransitionSequenceResult(
        activity_log_ids=[EXCEPTION_ACTIVITY_LOG_UUID, "status-log-id"],
        lifecycle_updated=True,
    )
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
                message=DEL_MSG,
                category=BusinessError.CATEGORY,
            ),
        },
    )

    record_workflow_failure_node(state)

    commands = mock_svc.apply_sequence.call_args[0]
    metadata = commands[0].metadata
    assert metadata["error"] == BusinessError.MISSING_DELIVERY_ADDRESS.value
    assert metadata["error_description"] == DEL_MSG
    mock_enqueue.assert_called_once_with(
        state,
        exception_activity_log_id=EXCEPTION_ACTIVITY_LOG_UUID,
    )
