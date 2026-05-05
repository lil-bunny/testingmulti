from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.workflow_service import WorkflowService
from app.api.deps import get_workflow_service
from app.core.logger import get_logger
from app.tools.email import check_ratecon_mail_payload
from app.tools.workflow_correlation import ratecon_shipment_in_workflow_correlation

from app.core.config import settings

router = APIRouter()
logger = get_logger(__name__)


def _merge_ratecon_classification_into_workflow_payload(
    payload: dict[str, Any], rc: dict[str, Any]
) -> None:
    """Copy ``check_ratecon_mail_payload`` fields onto the webhook dict for ``ratecon`` workflow."""
    for src, dest in (
        ("thread_id", "thread_id"),
        ("attachment_name", "ratecon_attachment_name"),
        ("attachment_uri", "ratecon_attachment_uri"),
        ("attachment_id", "ratecon_attachment_id"),
        ("attachment_mime", "ratecon_attachment_mime"),
    ):
        val = rc.get(src)
        if val is not None:
            payload[dest] = val
    if rc.get("attachment_unipile"):
        payload["ratecon_attachment_unipile"] = rc["attachment_unipile"]
    if rc.get("unipile_attachment_fetch"):
        payload["ratecon_unipile_attachment_fetch"] = rc["unipile_attachment_fetch"]


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

@router.post("/webhook/unipile/mail_thread_capture")
async def unipile_mail_thread_capture(
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        payload = {
            "event_type": "email_received",
            "webhook_name": raw.get("webhook_name"),
            **raw,
        }
        if payload['webhook_name'] != settings.UNIPILE_MAIL_THREAD_CAPTURE_WEBHOOK_NAME:
            raise HTTPException(status_code=400, detail="Invalid webhook")
        logger.info("Unipile mail thread capture payload: %s", payload)
        rc = check_ratecon_mail_payload(payload)
        if not rc["is_ratecon_mail"]:
            return {"message": "ignored", "reason": "not_ratecon_mail"}
        app_user = settings.TURVO_DEFAULT_APP_USER_ID
        
        corr = ratecon_shipment_in_workflow_correlation(rc["load_id"], app_user_id=app_user)
        if corr["in_workflow_correlation"]:
            return {
                "message": "ignored",
                "reason": "already_in_workflow_correlation",
                "in_workflow_correlation": True,
                "shipment_id": corr["shipment_id"],
                "load_id": corr["load_id"] or rc["load_id"],
            }
        payload["load_id"] = rc["load_id"]
        if corr.get("shipment_id"):
            payload["shipment_id"] = str(corr["shipment_id"]).strip()
        _merge_ratecon_classification_into_workflow_payload(payload, rc)
        result = await workflow_service.run(
            tenant_id="t3ra",
            workflow_name="ratecon",
            payload=payload,
        )
        if isinstance(result, dict):
            result["ran_ratecon_for_new_correlation"] = True
            result["shipment_id"] = corr["shipment_id"]
        return result
    except Exception as e:
        logger.exception("Unipile mail thread capture failed")
        raise HTTPException(status_code=500, detail=str(e)) from e

@router.post("/webhook/unipile")
async def unipile_webhook(
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        payload = {
            "event_type": "email_received",
            "webhook_name": raw.get("webhook_name"),
            **raw,
        }
        if payload['webhook_name'] != settings.UNIPILE_WEBHOOK_NAME:
            return {"message": "invalid webhook"}
        
        result = await workflow_service.run(
            tenant_id="t3ra",
            workflow_name="pod_lifecycle",
            payload=payload,
        )
        return result

    except Exception as e:
        logger.exception("Unipile webhook processing failed")
        raise HTTPException(status_code=500, detail=str(e))