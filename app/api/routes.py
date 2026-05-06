from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.services.workflow_service import WorkflowService
from app.api.deps import get_workflow_service
from app.core.logger import get_logger
from app.tools.email import check_ratecon_mail_payload

from app.core.config import settings

router = APIRouter()
logger = get_logger(__name__)


async def _run_pod_lifecycle_email_workflow(
    workflow_service: WorkflowService,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Unipile mail_received body → ``pod_lifecycle`` for tenant ``t3ra``."""
    return await workflow_service.run(
        tenant_id="t3ra",
        workflow_name="pod_lifecycle",
        payload=payload,
    )


def _merge_ratecon_classification_into_workflow_payload(
    payload: dict[str, Any], rc: dict[str, Any]
) -> None:
    """Copy ``check_ratecon_mail_payload`` fields onto the webhook dict (ratecon / pod_lifecycle paths)."""
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

@router.post("/webhook/unipile")
async def unipile_mail_thread_capture(
    request: Request,
    workflow_service: WorkflowService = Depends(get_workflow_service)
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        # Merge Unipile body first so event_type cannot be overridden by raw.
        payload = {**raw, "event_type": "email_received"}
        if payload['webhook_name'] != settings.UNIPILE_MAIL_THREAD_CAPTURE_WEBHOOK_NAME:
            raise HTTPException(status_code=400, detail="Invalid webhook")
        logger.info("Unipile mail thread capture payload: %s", payload)
        rc = check_ratecon_mail_payload(payload)
        if rc["is_ratecon_mail"]:
            payload["load_id"] = rc["load_id"]
            _merge_ratecon_classification_into_workflow_payload(payload, rc)
            result = await workflow_service.run(
                tenant_id="t3ra",
                workflow_name="ratecon",
                payload=payload,
            )
            if isinstance(result, dict):
                data = result.get("data") if isinstance(result.get("data"), dict) else {}
                result["shipment_id"] = data.get("shipment_id")
            return result

        _merge_ratecon_classification_into_workflow_payload(payload, rc)
        return await _run_pod_lifecycle_email_workflow(workflow_service, payload)
    except Exception as e:
        logger.exception("Unipile mail thread capture failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
