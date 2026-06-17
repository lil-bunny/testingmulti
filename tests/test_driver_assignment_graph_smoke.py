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

