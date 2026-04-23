import os

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import ROUTER_REGISTRY
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.builder import build_graph


def studio_graph():
    """
    Return a compiled graph for LangGraph Studio.

    Override defaults with:
    - STUDIO_TENANT_ID
    - STUDIO_WORKFLOW_NAME
    """
    tenant_id = os.getenv("STUDIO_TENANT_ID", "t3ra")
    workflow_name = os.getenv("STUDIO_WORKFLOW_NAME", "pod_lifecycle")

    workflow_repo = WorkflowRepository()
    tenant_repo = TenantRepository()

    base_graph = workflow_repo.get(workflow_name)
    tenant_overlay = tenant_repo.get_config(tenant_id).get(workflow_name, {})

    compiled = compile_graph(base_graph, tenant_overlay)
    return build_graph(compiled, ROUTER_REGISTRY)
