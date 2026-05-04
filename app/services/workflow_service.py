from app.services.execution_service import ExecutionService
from app.configs.workflow_template_contracts import WORKFLOW_TEMPLATE_CONTRACTS
from app.tools.workflow_correlation import get_workflow_for_thread, map_thread_to_workflow
from app.workflows.graph.builder import build_graph
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.routers import (
    convoy_router,
    event_type_router,
    noop_always_router,
    noop_followup_route,
    shipment_router,
    pod_exists_router,
    pod_missing_dispatch_router,
    pod_reply_router,
    pod_request_mark_router,
    pod_request_triggered_router,
    read_workflow_correlation_router
)
from typing import Optional
import uuid

from langsmith import traceable


ROUTER_REGISTRY = {
    "pod_exists": pod_exists_router,
    "pod_missing_dispatch": pod_missing_dispatch_router,
    "convoy": convoy_router,
    "shipment_router": shipment_router,
    "pod_reply": pod_reply_router,
    "event_type": event_type_router,
    "pod_request_triggered_router": pod_request_triggered_router,
    "pod_request_mark": pod_request_mark_router,
    "noop_always": noop_always_router,
    "noop_followup": noop_followup_route,
    "read_workflow_correlation": read_workflow_correlation_router,
}


class WorkflowService:

    def __init__(self, workflow_repo, tenant_repo):
        self.workflow_repo = workflow_repo
        self.tenant_repo = tenant_repo
        self.execution = ExecutionService()

    @traceable(run_type="chain", name="workflow_service_run")
    async def run(
        self,
        tenant_id: str,
        workflow_name: str,
        payload: Optional[dict] = None,
    ):
        contract = WORKFLOW_TEMPLATE_CONTRACTS.get(workflow_name)
        if not contract:
            raise Exception(f"Unknown workflow contract: {workflow_name}")

        payload = payload or {}
        missing_keys = [k for k in contract.required_state_keys if k not in payload]
        if missing_keys:
            raise Exception(
                f"Missing required payload keys for '{workflow_name}': {missing_keys}"
            )

        workflow_instance_id = self._resolve_workflow_instance_id(
            tenant_id=tenant_id,
            payload=payload,
        )
        payload["workflow_instance_id"] = workflow_instance_id
        payload["workflow_name"] = workflow_name
        if payload.get("thread_id"):
            map_thread_to_workflow(payload["thread_id"], workflow_instance_id)

        base_graph = self.workflow_repo.get(workflow_name)
        tenant_config = self.tenant_repo.get_config(tenant_id).get(workflow_name, {})

        compiled = compile_graph(base_graph, tenant_config)

        graph = build_graph(compiled, ROUTER_REGISTRY)

        return await self.execution.execute(
            graph=graph,
            tenant_id=tenant_id,
            workflow_instance_id=workflow_instance_id,
            payload=payload,
        )

    def _resolve_workflow_instance_id(self, tenant_id: str, payload: dict) -> str:
        explicit = payload.get("workflow_instance_id")
        if explicit:
            return explicit

        if payload.get("thread_id"):
            from_thread = get_workflow_for_thread(payload["thread_id"])
            if from_thread:
                return from_thread

        return str(uuid.uuid4())