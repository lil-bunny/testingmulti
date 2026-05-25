import os

from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_service import ROUTER_REGISTRY
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.builder import build_graph


def _build_studio_graph(*, workflow_name: str):
    tenant_slug = os.getenv("STUDIO_TENANT_SLUG", "t3ra")

    workflow_repo = WorkflowRepository()
    tenant_repo = TenantRepository()

    base_graph = workflow_repo.get(workflow_name)
    tenant_overlay = tenant_repo.get_config(tenant_slug).get(workflow_name, {})

    compiled = compile_graph(base_graph, tenant_overlay)
    return build_graph(compiled, ROUTER_REGISTRY)


def studio_graph():
    """
    Return the pod_lifecycle graph for LangGraph Studio.

    Override tenant with STUDIO_TENANT_SLUG.
    """
    return _build_studio_graph(workflow_name="pod_lifecycle")


def ratecon_studio_graph():
    """Return the ratecon graph for LangGraph Studio (see langgraph.json ``graphs.ratecon``)."""
    return _build_studio_graph(workflow_name="ratecon")


def load_tendering_studio_graph():
    """Return the load_tendering graph for LangGraph Studio (see langgraph.json ``graphs.load_tendering``)."""
    return _build_studio_graph(workflow_name="load_tendering")