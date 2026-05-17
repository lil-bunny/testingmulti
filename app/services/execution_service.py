import uuid
import asyncio
from app.domain.state import WorkflowState
from app.services.workflow_runs_service import WorkflowRunsService

from langsmith import traceable


class ExecutionService:

    def __init__(self):
        self.runs_service = WorkflowRunsService()

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
            shipment_id=payload.get("shipment_id"),
        )

        config = {"configurable": {"thread_id": workflow_lifecycle_id}}
        result = await asyncio.to_thread(graph.invoke, state, config)

        # TODO: discuss with team if this is needed, because in some workflows shipment_id is not received upfront, since we have FK lifecycle_id we can remove shipment_id from the workflow_runs table
        # backfill shipment_id if it was discovered during execution
        # result_data = result.data if hasattr(result, 'data') else (result.get("data") or {})
        # shipment_id = result_data.get("shipment_id")
        # if shipment_id and not payload.get("shipment_id"):
        #     self.runs_service.update_run_shipment_id(
        #         run_id=execution_id,
        #         shipment_id=shipment_id
        #     )
        if isinstance(result, dict):
            return result
        return result.model_dump()