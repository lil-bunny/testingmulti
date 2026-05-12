from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.workflow_classifier_service import WorkflowClassifierService
from app.services.workflow_service import WorkflowService
from app.api.deps import get_workflow_service
from app.core.logger import get_logger

from app.core.config import settings

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

@router.post("/webhook/unipile")
async def unipile_mail_thread_capture(
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        payload = {**raw, "event_type": "email_received"}

        if not payload['webhook_name'] == settings.UNIPILE_WEBHOOK_NAME:
            return {"message": "invalid webhook"}
        
        # classify workflow_type before langgraph exec: ratecon or pod_lifecycle
        workflow_classifier = WorkflowClassifierService()
        workflow_classification_result = workflow_classifier.classify_workflow_type(payload)

        workflow_name = workflow_classification_result.get("workflow_name")

        if workflow_name not in {"ratecon", "pod_lifecycle"}:
            return {"message": "invalid workflow type"}

        workflow_payload = {**payload, **workflow_classification_result} if workflow_name == "ratecon" else payload

        result = await workflow_service.run(
            tenant_id="t3ra",
            workflow_name=workflow_name,
            payload=workflow_payload,
        )

        if workflow_name == "ratecon" and isinstance(result, dict):
            data = result.get("data") if isinstance(result.get("data"), dict) else {}
            result["shipment_id"] = data.get("shipment_id")

        return result
    except Exception as e:
        logger.exception("Unipile mail thread capture failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
