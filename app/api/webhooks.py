from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.api.deps import get_workflow_service
from app.core.config import settings
from app.core.logger import get_logger
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.services.workflow_service import WorkflowService

router = APIRouter()
logger = get_logger(__name__)

WORKFLOW_NAME = "pod_lifecycle"
# Bump if you change the POST handler contract (OpenAPI / clients can compare).
WEBHOOK_HANDLER_VERSION = "v2-request-no-query-tenant"


class TurvoWebhookAck(BaseModel):
    status: str
    detail: str | None = None
    result: dict[str, Any] | None = None


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
    response_model=TurvoWebhookAck,
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
    workflow_service: WorkflowService = Depends(get_workflow_service),
) -> TurvoWebhookAck:
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
        return TurvoWebhookAck(
            status="skipped",
            detail="eventPayload.status.code.key must be 2116 and shipment_id/load_id must be present",
        )

    try:
        result = await workflow_service.run(
            tenant_id=workflow_tenant,
            workflow_name=WORKFLOW_NAME,
            payload=payload,
        )
        return TurvoWebhookAck(
            status="ok",
            result=result if isinstance(result, dict) else {"data": result},
        )

    except Exception as e:
        logger.exception("Turvo webhook workflow failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
