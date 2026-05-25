"""Compile ``load_tendering`` workflow template."""

from __future__ import annotations

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.workflows.compiler.compiler import compile_graph


def test_load_tendering_graph_compiles_with_gelita_overlay() -> None:
    wf = WorkflowRepository()
    base_graph = wf.get("load_tendering")
    tenant_overlay = TenantRepository().get_config("gelita").get("load_tendering", {})
    compile_graph(base_graph, tenant_overlay)
