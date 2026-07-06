"""Compile ``driver_assignment`` workflow template."""

from __future__ import annotations

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import ROUTER_REGISTRY
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.builder import build_graph


def test_driver_assignment_graph_compiles_with_t3ra_overlay() -> None:
    wf = WorkflowRepository()
    base_graph = wf.get("driver_assignment")
    tenant_overlay = TenantRepository().get_config("t3ra").get("driver_assignment", {})
    compiled = compile_graph(base_graph, tenant_overlay)
    build_graph(compiled, ROUTER_REGISTRY)


def test_driver_assignment_graph_schedules_before_started() -> None:
    edges = [tuple(edge) for edge in WORKFLOW_CONFIGS["driver_assignment"]["edges"]]
    assert ("resolve_workflow_lifecycle", "schedule_driver_reminders") in edges
    assert ("schedule_driver_reminders", "record_driver_assignment_started") in edges
    assert ("record_driver_assignment_started", "end") in edges
    assert ("record_tms_driver_success", "send_driver_details_confirmation") in edges
    assert ("send_driver_details_confirmation", "record_driver_details_confirmation_sent") in edges
    assert (
        "record_driver_details_confirmation_sent",
        "record_driver_assignment_completed",
    ) in edges
    assert ("record_driver_assignment_completed", "end") in edges


def test_driver_assignment_graph_routes_driver_details_email_received() -> None:
    routers = WORKFLOW_CONFIGS["driver_assignment"]["routers"]
    edges = [tuple(edge) for edge in WORKFLOW_CONFIGS["driver_assignment"]["edges"]]
    route_map = routers["route_event"]["map"]
    assert route_map["driver_details_email_received"] == "classify_driver_details"
    assert route_map["escalation_due"] == "get_shipment"
    delayed_map = routers["route_driver_assignment_delayed_event"]["map"]
    assert delayed_map["reminder_due"] == "check_driver_reminder_eligibility"
    assert delayed_map["escalation_due"] == "check_driver_escalation_eligibility"
    reminder_map = routers["check_driver_reminder_eligibility"]["map"]
    assert reminder_map["driver_already_assigned"] == "complete_driver_assignment_from_tms"
    assert ("complete_driver_assignment_from_tms", "end") in edges
    assert ("get_shipment", "route_driver_assignment_delayed_event") in edges
    assert ("escalate_driver_assignment", "end") in edges
    classify_map = routers["classify_driver_details"]["map"]
    assert classify_map["has_details"] == "resolve_turvo_driver"
    assert classify_map["insufficient"] == "route_tms_searchable"
    searchable_map = routers["route_tms_searchable"]["map"]
    assert searchable_map["searchable"] == "resolve_turvo_driver"
    assert searchable_map["follow_up_only"] == "send_driver_details_partial_follow_up"
    tms_map = routers["resolve_turvo_driver"]["map"]
    assert tms_map["assigned"] == "record_tms_driver_success"
    assert tms_map["follow_up"] == "record_tms_driver_not_resolved"
    assert ("record_tms_driver_not_resolved", "send_driver_details_partial_follow_up") in edges
    assert ("send_driver_details_partial_follow_up", "record_driver_reminder_sent") in edges
