"""
Tests for record_workflow_failure_node POD metadata enrichment.

Verifies that shipment_id and load_id from state are included in the
PENDING_REVIEW activity log metadata alongside the error fields.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.error_catalog import BusinessError, workflow_error_payload
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType
from app.workflows.nodes.error_handler import record_workflow_failure_node


TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
RUN_ID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def _state(**data) -> WorkflowState:
    return WorkflowState(
        tenant_id=TENANT_ID,
        tenant_slug="t3ra",
        execution_id=RUN_ID,
        data={
            "workflow_lifecycle_id": LIFECYCLE_ID,
            "error": workflow_error_payload(
                code=BusinessError.POD_ATTACHMENT_UPLOAD_FAILED.value,
                message=BusinessError.POD_ATTACHMENT_UPLOAD_FAILED.description,
                category=BusinessError.CATEGORY,
            ),
            **data,
        },
    )


def _exception_metadata(mock_svc: MagicMock) -> dict:
    mock_svc.apply_sequence.assert_called_once()
    exception_cmd = mock_svc.apply_sequence.call_args[0][0]
    assert exception_cmd.activity_type == ActivityType.EXCEPTION
    return exception_cmd.metadata


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_includes_shipment_id_in_metadata(
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state(
        shipment_id="SHP-999",
        load_id="LD-123",
    )

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)

    assert metadata["shipment_id"] == "SHP-999"
    assert metadata["load_id"] == "LD-123"
    assert metadata["error"] == BusinessError.POD_ATTACHMENT_UPLOAD_FAILED.value
    assert metadata["error_category"] == "business"
    assert metadata["error_description"] == BusinessError.POD_ATTACHMENT_UPLOAD_FAILED.description


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_omits_shipment_id_when_absent(
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state()

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)

    assert "shipment_id" not in metadata
    assert "load_id" not in metadata


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_includes_shipment_from_nested_shipment_dict(
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    """resolve_shipment_id resolves from state['shipment']['shipment_id'] too."""
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state(
        shipment={"shipment_id": "SHP-FROM-DICT"},
        load_id="LD-456",
    )

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)

    assert metadata["shipment_id"] == "SHP-FROM-DICT"
    assert metadata["load_id"] == "LD-456"


@patch("app.workflows.nodes.error_handler.enqueue_workflow_error_alert_from_state")
@patch("app.workflows.nodes.error_handler.LifecycleTransitionService")
def test_record_workflow_failure_pod_shipment_metadata_preserved(
    mock_svc_cls: MagicMock,
    mock_enqueue: MagicMock,
) -> None:
    """POD shipment fields are still written on workflow failure exceptions."""
    mock_svc = MagicMock()
    mock_svc_cls.return_value = mock_svc

    state = _state(
        tender_id="TND-1",
        pack_code="5366",
        shipment_id="SHP-777",
    )

    record_workflow_failure_node(state)

    metadata = _exception_metadata(mock_svc)

    assert metadata["shipment_id"] == "SHP-777"
