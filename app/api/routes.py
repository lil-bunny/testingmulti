import uuid
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse, Response

from app.core.config import settings
from app.core.logger import get_logger
from app.models.tenants import TenantSlug
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.communications.service import CommunicationsService
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.shipments_service import ShipmentsService
from app.services.t3ra_inbound_email_service import T3raInboundEmailService
from app.exceptions import TenantResolutionError
from app.services.unipile_tenant_resolution import resolve_unipile_tenant
from app.services.pod_lifecycle_ingress_service import PodLifecycleIngressService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async

router = APIRouter()
logger = get_logger(__name__)

WEBHOOK_HANDLER_VERSION = "v2-request-no-query-tenant"
TURVO_ROUTE_GATE_WORKFLOW = "ratecon"
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
    return TenantSlug.T3RA


@router.post(
    "/webhook/email",
    summary="Unipile email webhook events handler",
    description=(
        "Receives email webhook events after Bearer auth. "
        "L1 resolves tenant from recipient addresses (to/cc/bcc) against "
        "`tenants.settings.inbound_routing_emails`. "
        "L2 routes by tenant slug and classifies domain `event_type` per tenant."
    ),
)
async def webhook_email(request: Request):
    try:
        if request.headers.get("Authorization") != f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}":
            raise HTTPException(status_code=401, detail="Unauthorized")
        payload = await request.json()

        try:
            tenant = resolve_unipile_tenant(payload=payload)
        except TenantResolutionError as e:
            return {"message": f"invalid webhook: {str(e)}"}

        if tenant is None:
            return {"message": "invalid webhook"}

        # L2: route by resolved tenant slug to tenant ingress handler
        if tenant.tenant_slug == TenantSlug.GELITA:
            return await GelitaInboundEmailService().handle(payload=payload, tenant=tenant)
        if tenant.tenant_slug == TenantSlug.T3RA:
            return await T3raInboundEmailService().handle(payload=payload, tenant=tenant)

        logger.warning(
            "unipile webhook: unsupported tenant_slug=%r",
            tenant.tenant_slug,
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

    external_shipment_number = str(payload.get("shipment_id") or "").strip()
    lifecycle_shipment_uuid: str | None = None
    tenant_uuid = resolve_graph_tenant_to_uuid(workflow_tenant)
    if tenant_uuid and external_shipment_number:
        shipments_row = ShipmentsService().get_by_shipment_number(
            tenant_id=tenant_uuid,
            shipment_number=external_shipment_number,
        )
        if shipments_row:
            lifecycle_shipment_uuid = str(shipments_row.get("id") or "").strip() or None

    lifecycle_service = WorkflowLifecycleService()
    lifecycle = lifecycle_service.read_lifecycle(
        tenant_id=workflow_tenant,
        workflow_name=TURVO_ROUTE_GATE_WORKFLOW,
        shipment_id=lifecycle_shipment_uuid,
    )
    if not lifecycle.get("found"):
        logger.info(
            "Turvo webhook skipped: no ratecon workflow_lifecycle for shipment_number=%s "
            "shipments_row=%s load_id=%s",
            external_shipment_number,
            lifecycle_shipment_uuid,
            payload.get("load_id"),
        )
        return Response(status_code=status.HTTP_200_OK)

    lifecycle_id = str(lifecycle.get("lifecycle_id") or "").strip()
    if lifecycle_id and tenant_uuid:
        thread = CommunicationsService().resolve_thread_for_lifecycle(
            tenant_id=tenant_uuid,
            workflow_lifecycle_id=lifecycle_id,
        )
        if thread:
            payload["thread_id"] = thread
        else:
            logger.warning(
                "Turvo webhook: no thread_id from communications for ratecon lifecycle "
                "lifecycle_id=%s shipment_number=%s",
                lifecycle_id,
                external_shipment_number,
            )

    if tenant_uuid:
        duplicate = PodLifecycleIngressService().check_route_completed_duplicate(
            tenant_id=tenant_uuid,
            payload={
                **payload,
                **({"shipments_row_id": lifecycle_shipment_uuid} if lifecycle_shipment_uuid else {}),
            },
        )
        if duplicate.is_duplicate:
            logger.info(
                "Turvo webhook skipped: duplicate route_completed shipment_number=%s "
                "lifecycle_id=%s",
                external_shipment_number,
                duplicate.lifecycle_id,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "skipped": "duplicate_route_completed",
                    "lifecycle_id": duplicate.lifecycle_id,
                },
            )

    try:
        execution_id = str(uuid.uuid4())
        queued_payload = {**payload, "execution_id": execution_id}
        if lifecycle_shipment_uuid:
            queued_payload["shipments_row_id"] = lifecycle_shipment_uuid
        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": workflow_tenant,
                "workflow_name": LISTEN_TURVO_WORKFLOW_NAME,
                "payload": queued_payload,
            }
        )
        logger.info(
            "Turvo webhook queued task_id=%s execution_id=%s workflow_name=%s "
            "tenant_slug=%s shipment_id=%s shipments_row_id=%s thread_id=%s",
            task.id,
            execution_id,
            LISTEN_TURVO_WORKFLOW_NAME,
            workflow_tenant,
            payload.get("shipment_id"),
            lifecycle_shipment_uuid,
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
