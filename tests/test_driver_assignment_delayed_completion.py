"""Tests for driver assignment delayed-event completion routing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.workflows.graph.routers import driver_assignment_delayed_eligibility_router
from app.workflows.nodes.driver_assignment.nodes import complete_driver_assignment_from_tms


def _state(**data):
    return SimpleNamespace(
        data=dict(data),
        tenant_id=data.get("tenant_id"),
        execution_id=data.get("execution_id"),
    )


def test_delayed_eligibility_router_driver_already_assigned():
    state = _state(
        driver_assignment_eligible=False,
        driver_assignment_skip_reason="driver_already_assigned",
    )
    assert driver_assignment_delayed_eligibility_router(state) == "driver_already_assigned"


def test_delayed_eligibility_router_eligible():
    state = _state(driver_assignment_eligible=True)
    assert driver_assignment_delayed_eligibility_router(state) == "eligible"


def test_delayed_eligibility_router_other_skip():
    state = _state(
        driver_assignment_eligible=False,
        driver_assignment_skip_reason="already_completed",
    )
    assert driver_assignment_delayed_eligibility_router(state) == "skip"


@patch("app.workflows.nodes.driver_assignment.nodes.DriverAssignmentActivityService")
def test_complete_driver_assignment_from_tms_delegates_to_service(mock_cls: MagicMock):
    state = _state(workflow_lifecycle_id="wl-1", tenant_id="t-1", execution_id="run-1")
    complete_driver_assignment_from_tms(state)
    mock_cls.return_value.complete_when_driver_already_in_tms.assert_called_once_with(state)


@patch("app.services.driver_assignment.activity_service.DriverAssignmentShipmentDetailsService")
@patch("app.services.driver_assignment.activity_service.WorkflowReminderCancelService")
def test_complete_when_driver_already_in_tms_persists_from_turvo(
    mock_cancel_cls: MagicMock,
    mock_details_cls: MagicMock,
):
    from app.services.driver_assignment.activity_service import DriverAssignmentActivityService

    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "pending_review",
        "sub_status": "reminder_1_sent",
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    state = _state(
        workflow_lifecycle_id="wl-1",
        tenant_id="t-1",
        execution_id="run-1",
        shipment={"details": {"carrierOrder": [{"deleted": False, "primaryDriver": {"id": "1", "name": "Alex"}}]}},
    )

    svc.complete_when_driver_already_in_tms(state)

    mock_details_cls.return_value.persist_from_turvo_shipment.assert_called_once_with(state)
    assert state.data["tms_resolution"] == "skipped_already_assigned"
    mock_cancel_cls.return_value.cancel_all.assert_called_once_with(lifecycle_id="wl-1")
    activity.record_sequence.assert_called_once()


@patch("app.services.driver_assignment.activity_service.WorkflowReminderCancelService")
def test_complete_when_driver_already_in_tms_sets_resolution_and_records(
    mock_cancel_cls: MagicMock,
):
    from app.services.driver_assignment.activity_service import DriverAssignmentActivityService

    activity = MagicMock()
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "pending_review",
        "sub_status": "reminder_1_sent",
    }
    svc = DriverAssignmentActivityService(
        activity_log_service=activity,
        lifecycle_service=lifecycle,
    )
    state = _state(
        workflow_lifecycle_id="wl-1",
        tenant_id="t-1",
        execution_id="run-1",
    )

    svc.complete_when_driver_already_in_tms(state)

    assert state.data["tms_resolution"] == "skipped_already_assigned"
    mock_cancel_cls.return_value.cancel_all.assert_called_once_with(lifecycle_id="wl-1")
    activity.record_sequence.assert_called_once()
