from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.services.workflow_service import WorkflowService
from app.api.deps import get_workflow_service
from app.core.logger import get_logger

router = APIRouter()
logger = get_logger(__name__)


class RunWorkflowRequest(BaseModel):
    tenant_id: str
    workflow_name: str
    payload: dict = Field(default_factory=dict)


@router.post("/workflows/run")
async def run_workflow(
    request: RunWorkflowRequest,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    try:
        result = await workflow_service.run(
            tenant_id=request.tenant_id,
            workflow_name=request.workflow_name,
            payload=request.payload,
        )
        return result

    except Exception as e:
        logger.exception("Workflow execution failed")
        raise HTTPException(status_code=500, detail=str(e))