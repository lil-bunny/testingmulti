"""Router tests for pod_missing_dispatch on reminder_due POD exists."""

from __future__ import annotations

from app.domain.state import WorkflowState
from app.workflows.graph.routers import pod_missing_dispatch_router


def _state(**data) -> WorkflowState:
    return WorkflowState(tenant_id="t", tenant_slug="t3ra", execution_id="run-1", data=data)


def test_exists_on_reminder_when_pod_found_on_reminder_due():
    route = pod_missing_dispatch_router(
        _state(event_type="reminder_due", pod_exists=True)
    )
    assert route == "exists_on_reminder"


def test_exists_when_pod_found_on_route_completed():
    route = pod_missing_dispatch_router(
        _state(event_type="route_completed", pod_exists=True)
    )
    assert route == "exists"


def test_send_now_when_pod_missing_on_reminder_due():
    route = pod_missing_dispatch_router(
        _state(event_type="reminder_due", pod_exists=False)
    )
    assert route == "send_now"
