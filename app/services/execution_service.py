import uuid
import asyncio

from app.domain.state import WorkflowState
from app.domain.gelita.routing_guide_lifecycle import optional_routing_guide_attempt
from app.services.communications.service import CommunicationsService
from app.services.workflow_runs_service import WorkflowRunsService

from langsmith import traceable


class ExecutionService:

    def __init__(self):
        self.runs_service = WorkflowRunsService()
        self._communications = CommunicationsService()

    @traceable(run_type="chain", name="workflow_execute")
    async def execute(
        self,
        graph,
        tenant_id: str,
        tenant_slug: str,
        workflow_lifecycle_id: str,
        payload: dict,
        execution_id: str | None = None,
    ):
        execution_id = str(execution_id).strip() if execution_id else ""

        if not execution_id:
            execution_id = str(uuid.uuid4())

        state = WorkflowState(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            execution_id=execution_id,
            data=payload,
        )
        state.data["tenant_id"] = tenant_id
        state.data["tenant_slug"] = tenant_slug
        self.runs_service.record_workflow_run(
            run_id=execution_id,
            tenant_id=tenant_id,
            event_type=payload.get("event_type"),
            workflow_lifecycle_id=workflow_lifecycle_id,
        )

        communication_id = payload.get("communication_id")
        event_type = str(payload.get("event_type") or "").strip()
        wl_id = str(workflow_lifecycle_id or "").strip() or None
        if communication_id:
            comm_id = str(communication_id)
            if event_type == "carrier_email_received":
                self._communications.link_carrier_email_received_communication(
                    communication_id=comm_id,
                    workflow_run_id=execution_id,
                    workflow_lifecycle_id=wl_id,
                    routing_guide_attempt=optional_routing_guide_attempt(
                        payload.get("routing_guide_attempt")
                    ),
                )
            else:
                self._communications.link_inbound_to_workflow_run(
                    communication_id=comm_id,
                    workflow_run_id=execution_id,
                    workflow_lifecycle_id=wl_id,
                )
            thread_id = str(payload.get("thread_id") or "").strip()
            if thread_id and wl_id:
                self._communications.link_workflow_run_to_thread(
                    tenant_id=tenant_id,
                    thread_id=thread_id,
                    workflow_run_id=execution_id,
                    workflow_lifecycle_id=wl_id,
                )

        config = {"configurable": {"thread_id": workflow_lifecycle_id}}
        result = await asyncio.to_thread(graph.invoke, state, config)

        if isinstance(result, dict):
            return result
        return result.model_dump()
