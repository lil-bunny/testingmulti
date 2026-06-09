"""Smoke tests for builder-level global error interception."""

from __future__ import annotations

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import ROUTER_REGISTRY
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.builder import ERROR_NODE, build_graph


def test_load_tendering_graph_builds_with_injected_failure_node() -> None:
    wf = WorkflowRepository()
    base_graph = wf.get("load_tendering")
    tenant_overlay = TenantRepository().get_config("gelita").get("load_tendering", {})
    compiled = compile_graph(base_graph, tenant_overlay)

    assert ERROR_NODE not in compiled["nodes"]

    graph = build_graph(compiled, ROUTER_REGISTRY)
    assert graph is not None
