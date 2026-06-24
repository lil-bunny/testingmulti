"""Thin driver-details workflow nodes delegate to services."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.tools.driver_details import HAS_DETAILS, INSUFFICIENT
from app.workflows.graph.routers import (
    driver_details_partial_router,
    driver_details_router,
    event_type_router,
)
from app.workflows.nodes.driver_assignment.nodes import (
    classify_driver_details,
    record_driver_details_email_received,
    send_driver_details_partial_follow_up,
)


def test_event_type_router_driver_details_email_received() -> None:
    state = SimpleNamespace(data={"event_type": "driver_details_email_received"})
    assert event_type_router(state) == "driver_details_email_received"


def test_driver_details_router_maps_decisions() -> None:
    state = SimpleNamespace(data={"driver_details_decision": HAS_DETAILS})
    assert driver_details_router(state) == HAS_DETAILS
    state.data["driver_details_decision"] = "bogus"
    assert driver_details_router(state) == "do_nothing"


def test_classify_driver_details_delegates_to_service() -> None:
    state = SimpleNamespace(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={"thread_id": "t1", "body": "Driver John"},
    )
    mock_result = MagicMock()
    mock_result.to_state_patch.return_value = {
        "driver_details_decision": HAS_DETAILS,
        "driver_details_reason": "ok",
    }
    with patch(
        "app.workflows.nodes.driver_assignment.nodes.DriverDetailsClassificationService"
    ) as svc_cls:
        svc_cls.return_value.classify_from_state.return_value = mock_result
        out = classify_driver_details(state)

    assert out is state
    assert state.data["driver_details_decision"] == HAS_DETAILS
    svc_cls.return_value.classify_from_state.assert_called_once_with(state)


def test_driver_details_partial_router():
    state = SimpleNamespace(
        data={
            "driver_details_extraction": {
                "driver": {"name": "John", "phone": None, "email": None},
            }
        }
    )
    assert driver_details_partial_router(state) == "partial_fields"
    state.data["driver_details_extraction"] = {"driver": {}}
    assert driver_details_partial_router(state) == "no_partial_fields"


def test_send_driver_details_partial_follow_up_delegates_to_ingress() -> None:
    state = SimpleNamespace(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={"workflow_lifecycle_id": "lc-1", "thread_id": "t1"},
    )
    mock_result = MagicMock()
    mock_result.sent = True
    mock_result.error = None
    mock_result.communication_id = "comm-1"
    mock_result.reminder_step = 2
    with patch(
        "app.workflows.nodes.driver_assignment.nodes.DriverAssignmentIngressService"
    ) as svc_cls:
        svc_cls.return_value.send_partial_details_follow_up_email.return_value = mock_result
        out = send_driver_details_partial_follow_up(state)

    assert out is state
    assert state.data["driver_reminder_sent"] is True
    assert state.data["driver_reminder_is_partial_follow_up"] is True
    assert state.data["reminder_step"] == 2
    assert state.data["communication_id"] == "comm-1"


def test_send_driver_details_partial_follow_up_sets_skip_bump_at_cap() -> None:
    state = SimpleNamespace(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={"workflow_lifecycle_id": "lc-1", "thread_id": "t1"},
    )
    mock_result = MagicMock()
    mock_result.sent = True
    mock_result.error = None
    mock_result.communication_id = "comm-1"
    mock_result.reminder_step = 4
    mock_result.skip_sub_status_bump = True
    with patch(
        "app.workflows.nodes.driver_assignment.nodes.DriverAssignmentIngressService"
    ) as svc_cls:
        svc_cls.return_value.send_partial_details_follow_up_email.return_value = mock_result
        send_driver_details_partial_follow_up(state)

    assert state.data["driver_reminder_skip_sub_status_bump"] is True
    assert state.data["reminder_step"] == 4


def test_record_driver_details_email_received_delegates_to_activity_service() -> None:
    state = SimpleNamespace(
        tenant_id="tenant-1",
        data={"driver_details_decision": HAS_DETAILS},
    )
    with patch(
        "app.workflows.nodes.driver_assignment.nodes.DriverAssignmentActivityService"
    ) as svc_cls:
        record_driver_details_email_received(state)
    svc_cls.return_value.record_driver_details_email_received.assert_called_once_with(
        state
    )


def test_record_driver_details_skipped_at_node_when_insufficient() -> None:
    state = SimpleNamespace(
        tenant_id="tenant-1",
        data={"driver_details_decision": INSUFFICIENT},
    )
    with patch(
        "app.workflows.nodes.driver_assignment.nodes.DriverAssignmentActivityService"
    ) as svc_cls:
        record_driver_details_email_received(state)
    svc_cls.return_value.record_driver_details_email_received.assert_called_once_with(
        state
    )
