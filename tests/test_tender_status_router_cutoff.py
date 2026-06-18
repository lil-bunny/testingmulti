"""Tests for load-tendering tender_status_router delivery cutoff."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.state import WorkflowState
from app.workflows.graph.routers import tender_status_router
from tests.fixtures.tenant_settings import load_tenant_settings_dev


def _state(*, event_type: str, delivery_date: str, tenant_settings: dict | None = None) -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={
            "event_type": event_type,
            "tender_id": "tender-1",
            "workflow_lifecycle_id": "wl-1",
            "tenant_settings": tenant_settings or load_tenant_settings_dev("gelita"),
            "tender": {
                "load_type": "ltl",
                "delivery_date": delivery_date,
            },
        },
    )


@patch("app.workflows.graph.routers.is_past_delivery_cutoff", return_value=False)
def test_tender_status_router_before_delivery_cutoff(_mock_cutoff) -> None:
    assert tender_status_router(_state(event_type="reminder_due", delivery_date="2026-06-20")) == "reminder_due"


@patch("app.workflows.graph.routers.is_past_delivery_cutoff", return_value=True)
def test_tender_status_router_past_delivery_cutoff_routes_completed(_mock_cutoff) -> None:
    assert tender_status_router(_state(event_type="escalation_due", delivery_date="2026-06-20")) == "completed"


def test_tender_status_router_no_cutoff_config_allows_event() -> None:
    settings = load_tenant_settings_dev("gelita")
    reminders = dict(settings["load_tendering"]["reminders"])
    reminders.pop("delivery_cutoff", None)
    settings = dict(settings)
    settings["load_tendering"] = dict(settings["load_tendering"])
    settings["load_tendering"]["reminders"] = reminders

    state = _state(
        event_type="reminder_due",
        delivery_date="2020-01-01",
        tenant_settings=settings,
    )
    assert tender_status_router(state) == "reminder_due"
