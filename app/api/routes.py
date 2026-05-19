import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.t3ra_inbound_email_service import T3raInboundEmailService
from app.services.unipile_tenant_resolution import resolve_unipile_tenant
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async

router = APIRouter()
logger = get_logger(__name__)

WEBHOOK_HANDLER_VERSION = "v2-request-no-query-tenant"
LISTEN_TURVO_WORKFLOW_NAME = "pod_lifecycle"


def _resolve_workflow_tenant_id(override: Optional[str]) -> str:
    """
    Webhooks (e.g. Turvo) often cannot send custom query params. Precedence: optional
    X-Workflow-Tenant-Id header, then TURVO_WEBHOOK_WORKFLOW_TENANT_ID, then STUDIO_TENANT_SLUG.
    """
    for candidate in (
        (override or "").strip() or None,
        (settings.TURVO_WEBHOOK_WORKFLOW_TENANT_ID or "").strip() or None,
        (settings.STUDIO_TENANT_SLUG or "").strip() or None,
    ):
        if candidate:
            return candidate
    return "t3ra"


@router.post(
    "/webhook/email",
    summary="Unipile email webhook events handler",
    description=(
        "Receives email webhook events after Bearer auth. "
        "`webhook_name` must match `tenants.settings.email_webhook_name`. "
        "L1 routes by tenant slug; L2 classifies domain `event_type` per tenant."
    ),
)
async def webhook_email(request: Request):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        payload = await request.json()

        tenant = resolve_unipile_tenant(payload=payload)
        if tenant is None:
            return {"message": "invalid webhook"}
        
        # L1 routing by tenant slug using webhook_name
        if tenant.tenant_slug == "gelita":
            return await GelitaInboundEmailService().handle(payload=payload, tenant=tenant)
        if tenant.tenant_slug == "t3ra":
            return await T3raInboundEmailService().handle(payload=payload, tenant=tenant)

        logger.warning(
            "unipile webhook: unsupported tenant_slug=%r webhook_name=%r",
            tenant.tenant_slug,
            payload.get("webhook_name"),
        )
        return {"message": "invalid webhook"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Unipile mail thread capture failed")
        raise HTTPException(status_code=500, detail="Internal error") from e


@router.post(
    "/webhook/turvo",
    summary="Turvo status webhook (no query params; see header + env for tenant)",
    openapi_extra={
        "parameters": [
            {
                "name": "X-Workflow-Tenant-Id",
                "in": "header",
                "required": False,
                "schema": {"type": "string"},
                "description": (
                    "Optional workflow tenant key (e.g. t3ra). "
                    "Else TURVO_WEBHOOK_WORKFLOW_TENANT_ID, STUDIO_TENANT_SLUG, or t3ra."
                ),
            }
        ]
    },
)
async def listen_turvo_status(request: Request) -> Response:
    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from e

    override = request.headers.get("X-Workflow-Tenant-Id")
    workflow_tenant = _resolve_workflow_tenant_id(override)
    payload = map_turvo_status_webhook_to_payload(body)
    if payload is None or not payload.get("shipment_id"):
        logger.info("Turvo webhook skipped: status key is not 2116 or shipment/load id missing")
        return Response(status_code=status.HTTP_200_OK)

    lifecycle_service = WorkflowLifecycleService()
    lifecycle = lifecycle_service.read_lifecycle(
        tenant_id=workflow_tenant,
        workflow_name="ratecon",
        shipment_id=payload.get("shipment_id"),
    )
    if not lifecycle.get("found"):
        logger.info(
            "Turvo webhook skipped: no workflow_correlation row for shipment/load %s",
            payload.get("shipment_id"),
        )
        return Response(status_code=status.HTTP_200_OK)
    thread = lifecycle.get("email_thread_id")
    if thread:
        payload["thread_id"] = thread.strip()

    try:
        execution_id = str(uuid.uuid4())
        queued_payload = {**payload, "execution_id": execution_id}
        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": workflow_tenant,
                "workflow_name": LISTEN_TURVO_WORKFLOW_NAME,
                "payload": queued_payload,
            }
        )
        logger.info(
            "Turvo webhook queued task_id=%s execution_id=%s workflow_name=%s "
            "tenant_slug=%s shipment_id=%s thread_id=%s",
            task.id,
            execution_id,
            LISTEN_TURVO_WORKFLOW_NAME,
            workflow_tenant,
            payload.get("shipment_id"),
            payload.get("thread_id"),
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"execution_id": execution_id},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Turvo webhook queueing failed")
        raise HTTPException(status_code=500, detail="Internal error") from e
