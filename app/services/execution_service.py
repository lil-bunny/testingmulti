import uuid
import asyncio
from app.domain.state import WorkflowState

from langsmith import traceable


class ExecutionService:

    @traceable(run_type="chain", name="workflow_execute")
    async def execute(
        self,
        graph,
        tenant_id: str,
        workflow_instance_id: str,
        payload: dict,
    ):

        state = WorkflowState(
            tenant_id=tenant_id,
            execution_id=str(uuid.uuid4()),
            data=payload,
        )
        state.data["tenant_id"] = tenant_id

        config = {"configurable": {"thread_id": workflow_instance_id}}
        result = await asyncio.to_thread(graph.invoke, state, config)

        if isinstance(result, dict):
            return result
        return result.model_dump()