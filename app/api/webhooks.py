from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.tasks.workflows import run_workflow_async
from app.tools.workflow_correlation import read_by_key

router = APIRouter()
logger = get_logger(__name__)

WORKFLOW_NAME = "pod_lifecycle"
# Bump if you change the POST handler contract (OpenAPI / clients can compare).
WEBHOOK_HANDLER_VERSION = "v2-request-no-query-tenant"


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


@router.get(
    "/webhooks/turvo/_handler_version",
    summary="Which Turvo webhook code is loaded (use if POST still asks for query tenant_id)",
    tags=["diagnostics"],
)
def turvo_webhook_handler_version() -> dict[str, Any]:
    """If this 404s or shows old data, the server is not running this codebase / not reloaded."""
    return {
        "requires_query_tenant_id": False,
        "handler_version": WEBHOOK_HANDLER_VERSION,
        "post_path": "/api/listen_turvo_status",
    }


@router.post(
    "/listen_turvo_status",
    summary="[v2] Turvo status webhook (no query params; see header + env for tenant)",
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
    if payload is None:
        logger.info("Turvo webhook skipped: status key is not 2116 or shipment/load id missing")
        return Response(status_code=status.HTTP_200_OK)

    sid = payload.get("shipment_id") or ""
 
    correlation_key = str(sid).strip() 
    correlation = read_by_key(correlation_key)
    if not correlation.get("found"):
        logger.info("Turvo webhook skipped: no workflow_correlation row for shipment/load %s", correlation_key)
        return Response(status_code=status.HTTP_200_OK)
    thread = (correlation.get("payload") or {}).get("email_thread_id") or ""
    if thread.strip():
        payload["thread_id"] = thread.strip()

    try:
        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_id": workflow_tenant,
                "workflow_name": WORKFLOW_NAME,
                "payload": payload,
            }
        )
        logger.info(
            "Turvo webhook queued task_id=%s workflow_name=%s tenant_id=%s shipment_id=%s thread_id=%s",
            task.id,
            WORKFLOW_NAME,
            workflow_tenant,
            payload.get("shipment_id"),
            payload.get("thread_id"),
        )
        return Response(status_code=status.HTTP_200_OK)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Turvo webhook queueing failed")
        raise HTTPException(status_code=500, detail="Internal error") from e
