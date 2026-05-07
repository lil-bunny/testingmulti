from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from app.core.logger import get_logger
from app.tasks.workflows import run_workflow_async
from app.tools.email import check_ratecon_mail_payload

from app.core.config import settings

router = APIRouter()
logger = get_logger(__name__)




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


@router.post("/webhook/unipile")
async def unipile_mail_thread_capture(
    request: Request,
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        # Merge Unipile body first so event_type cannot be overridden by raw.
        #webhook name coming from raw 
        payload = {**raw, "event_type": "email_received"}

        rc = check_ratecon_mail_payload(payload)
       
        if rc["is_ratecon_mail"] and payload['webhook_name'] == settings.UNIPILE_WEBHOOK_NAME:
            payload["load_id"] = rc["load_id"]
            _merge_ratecon_classification_into_workflow_payload(payload, rc)
            task = run_workflow_async.apply_async(
                kwargs={
                    "tenant_id": "t3ra",
                    "workflow_name": "ratecon",
                    "payload": payload,
                }
            )
            logger.info(
                "Unipile webhook queued task_id=%s workflow_name=%s tenant_id=%s thread_id=%s load_id=%s",
                task.id,
                "ratecon",
                "t3ra",
                payload.get("thread_id"),
                payload.get("load_id"),
            )
            return Response(status_code=status.HTTP_200_OK)
        elif payload['webhook_name'] == settings.UNIPILE_WEBHOOK_NAME:
            task = run_workflow_async.apply_async(
                kwargs={
                    "tenant_id": "t3ra",
                    "workflow_name": "pod_lifecycle",
                    "payload": payload,
                }
            )
            logger.info(
                "Unipile webhook queued task_id=%s workflow_name=%s tenant_id=%s thread_id=%s shipment_id=%s",
                task.id,
                "pod_lifecycle",
                "t3ra",
                payload.get("thread_id"),
                payload.get("shipment_id"),
            )
            return Response(status_code=status.HTTP_200_OK)
        else:
            return {"message": "invalid webhook"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unipile mail thread capture failed")
        raise HTTPException(status_code=500, detail="Internal error") from e
