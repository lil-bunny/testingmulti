from app.domain.tenant_settings.registry import normalize_tenant_settings_dict
from app.services.execution_service import ExecutionService
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.configs.workflow_template_contracts import WORKFLOW_TEMPLATE_CONTRACTS
from app.workflows.graph.builder import build_graph
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.routers import (
    carrier_ack_router,
    event_type_router,
    tender_status_router,
    load_type_router,
    shipment_router,
    pod_exists_router,
    pod_missing_dispatch_router,
    pod_request_triggered_router,
    read_workflow_lifecycle_router,
)
from typing import Optional

from langsmith import traceable


ROUTER_REGISTRY = {
    "pod_exists": pod_exists_router,
    "pod_missing_dispatch": pod_missing_dispatch_router,
    "shipment_router": shipment_router,
    "event_type": event_type_router,
    "pod_request_triggered_router": pod_request_triggered_router,
    "read_workflow_lifecycle_router": read_workflow_lifecycle_router,
    "load_type_router": load_type_router,
    "tender_status_router": tender_status_router,
    "carrier_ack_router": carrier_ack_router,
}


class WorkflowService:

    def __init__(self, workflow_repo, tenant_repo):
        self.workflow_repo = workflow_repo
        self.tenant_repo = tenant_repo
        self.execution = ExecutionService()
        self.lifecycle_service = WorkflowLifecycleService()
        self.tenants_service = TenantsService()

    async def run(
        self,
        tenant_slug: str,
        workflow_name: str,
        payload: Optional[dict] = None,
    ):
        payload = payload or {}
        tenant_row = self.tenants_service.get_by_slug(tenant_slug)
        if tenant_row is None:
            raise Exception(f"Unknown tenant slug: {tenant_slug!r}")
        tenant_id = tenant_row["id"]

        payload["tenant_id"] = tenant_id
        payload["tenant_slug"] = tenant_slug
        payload["tenant_settings"] = normalize_tenant_settings_dict(
            tenant_slug,
            tenant_row.get("settings") or {},
        )

        lifecycle = self.lifecycle_service.resolve_or_create_lifecycle(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            payload=payload,
        )
        workflow_lifecycle_id = lifecycle.workflow_lifecycle_id
        payload["workflow_lifecycle_id"] = workflow_lifecycle_id
        payload["workflow_name"] = workflow_name

        event_type = payload.get("event_type")
        traced = traceable(
            run_type="chain",
            name=f"workflow:{workflow_name}",
        )(self._run_impl)
        return await traced(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            workflow_name=workflow_name,
            payload=payload,
            langsmith_extra={
                "metadata": {
                    "thread_id": workflow_lifecycle_id,
                    "workflow_lifecycle_id": workflow_lifecycle_id,
                    "tenant_id": tenant_id,
                    "tenant_slug": tenant_slug,
                    "event_type": event_type,
                    "shipment_id": payload.get("shipment_id"),
                    "tender_id": payload.get("tender_id"),
                    "order_number": payload.get("order_number"),
                    "email_thread_id": payload.get("email_thread_id") or payload.get("thread_id"),
                }
            },
        )

    async def _run_impl(
        self,
        tenant_id: str,
        tenant_slug: str,
        workflow_name: str,
        payload: Optional[dict] = None,
    ):
        contract = WORKFLOW_TEMPLATE_CONTRACTS.get(workflow_name)
        if not contract:
            raise Exception(f"Unknown workflow contract: {workflow_name}")

        payload = payload or {}
        workflow_lifecycle_id = str(payload.get("workflow_lifecycle_id") or "").strip()
        if not workflow_lifecycle_id:
            raise Exception("Missing workflow_lifecycle_id")
        missing_keys = [k for k in contract.required_state_keys if k not in payload]
        if missing_keys:
            raise Exception(
                f"Missing required payload keys for '{workflow_name}': {missing_keys}"
            )

        base_graph = self.workflow_repo.get(workflow_name)
        tenant_config = self.tenant_repo.get_config(tenant_slug).get(workflow_name, {})

        compiled = compile_graph(base_graph, tenant_config)

        graph = build_graph(compiled, ROUTER_REGISTRY)

        execution_id = payload.get("execution_id", None)
        # execution_id = (
        #     pre_assigned.strip()
        #     if isinstance(pre_assigned, str) and pre_assigned.strip()
        #     else None
        # )

        return await self.execution.execute(
            graph=graph,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            workflow_lifecycle_id=workflow_lifecycle_id,
            payload=payload,
            execution_id=execution_id,
        )