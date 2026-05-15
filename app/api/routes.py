import uuid

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from app.api.deps import get_workflow_service
from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.workflow_classifier_service import WorkflowClassifierService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_service import WorkflowService
from app.tasks.workflows import run_workflow_async

router = APIRouter()
logger = get_logger(__name__)

# Turvo listen handler — bump if POST contract changes (OpenAPI / clients).
WEBHOOK_HANDLER_VERSION = "v2-request-no-query-tenant"
LISTEN_TURVO_WORKFLOW_NAME = "pod_lifecycle"


class RunWorkflowRequest(BaseModel):
    tenant_id: str
    workflow_name: str
    payload: dict = Field(default_factory=dict)


def _resolve_workflow_tenant_id(override: Optional[str]) -> str:
    """
    Webhooks (e.g. Turvo) often cannot send custom query params. Precedence: optional
    X-Workflow-Tenant-Id header, then TURVO_WEBHOOK_WORKFLOW_TENANT_ID, then STUDIO_TENANT_ID.

    Note: body `tenantId` is Turvo's id, not necessarily app/configs/tenant_configs.py keys.
    """
    for candidate in (
        (override or "").strip() or None,
        (settings.TURVO_WEBHOOK_WORKFLOW_TENANT_ID or "").strip() or None,
        (settings.STUDIO_TENANT_ID or "").strip() or None,
    ):
        if candidate:
            return candidate
    return "t3ra"


@router.post(
    "/webhook/unipile",
    summary="Unipile mail gateway webhook handler",
    description="Receives Unipile 'email_received' webhook events, classifies workflow type, and schedules the corresponding workflow for execution."
)
async def unipile_mail_thread_capture(
    request: Request
):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        raw = await request.json()
        payload = {**raw, "event_type": "email_received"}

        if not payload["webhook_name"] == settings.UNIPILE_WEBHOOK_NAME:
            return {"message": "invalid webhook"}

        # classify workflow_type before langgraph exec: ratecon or pod_lifecycle
        workflow_classifier = WorkflowClassifierService()
     
        workflow_classification_result = workflow_classifier.classify_workflow_type(payload)

        workflow_name = workflow_classification_result.get("workflow_name")

        if workflow_name not in {"ratecon", "pod_lifecycle", "load_tendering"}:
            return {"message": "invalid workflow type"}

        # tenants.id UUID for data_imports; resolve per workflow / header when multi-tenant expands.
        data_import_tenant_id = settings.GELLITA_TENANT_ID
        await process_email_webhook_attachment_import(
            payload=payload,
            workflow_name=str(workflow_name),
            data_import_tenant_id=data_import_tenant_id,
            data_import_data_type="load_tendering"
        )

        if workflow_name == "load_tendering":
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "success"},
            )

        workflow_payload = (
            {**payload, **workflow_classification_result}
            if workflow_name == "ratecon"
            else payload
        )
        execution_id = str(uuid.uuid4())
        workflow_payload = {**workflow_payload, "execution_id": execution_id}
        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_id": "t3ra",
                "workflow_name": workflow_name,
                "payload": workflow_payload,
            }
        )

        logger.info(
            "Unipile webhook queued task_id=%s execution_id=%s workflow_name=%s tenant_id=%s thread_id=%s load_id=%s",
            task.id,
            execution_id,
            workflow_name,
            payload.get("tenant_id"),
            payload.get("thread_id"),
            payload.get("load_id"),
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"execution_id": execution_id},
        )
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
                "description": "Optional. Workflow tenant key from app/configs/tenant_configs.py (e.g. t3ra). If omitted, uses TURVO_WEBHOOK_WORKFLOW_TENANT_ID, then STUDIO_TENANT_ID, else t3ra.",
            }
        ]
    },
)
async def listen_turvo_status(
    request: Request,
) -> Response:
    """
    Accepts raw Turvo webhook JSON (POST body only; **no** `tenant_id` query param).

    Optional header `X-Workflow-Tenant-Id` overrides the workflow tenant; otherwise
    use env: `TURVO_WEBHOOK_WORKFLOW_TENANT_ID` → `STUDIO_TENANT_ID` → default `t3ra`.
    """
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
                "tenant_id": workflow_tenant,
                "workflow_name": LISTEN_TURVO_WORKFLOW_NAME,
                "payload": queued_payload,
            }
        )
        logger.info(
            "Turvo webhook queued task_id=%s execution_id=%s workflow_name=%s tenant_id=%s shipment_id=%s thread_id=%s",
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
