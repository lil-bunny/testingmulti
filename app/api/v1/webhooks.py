"""v1 inbound webhook endpoints (Unipile email, Turvo status)."""

import uuid
from typing import Annotated, Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.security import unipile_webhook_bearer

from app.core.config import settings
from app.core.logger import get_logger
from app.exceptions import TenantResolutionError
from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload
from app.models.tenants import TenantSlug
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.communications.service import CommunicationsService
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.pod_lifecycle_ingress_service import PodLifecycleIngressService
from app.services.shipments_service import ShipmentsService
from app.services.t3ra_inbound_email_service import T3raInboundEmailService
from app.services.unipile_tenant_resolution import resolve_unipile_tenant
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async

router = APIRouter(prefix="/webhook", tags=["webhooks"])
logger = get_logger(__name__)

TURVO_ROUTE_GATE_WORKFLOW = "ratecon"
LISTEN_TURVO_WORKFLOW_NAME = "pod_lifecycle"


def _resolve_workflow_tenant_id(override: Optional[str]) -> str:
    """
    Webhooks (e.g. Turvo) often cannot send custom query params. Precedence: optional
    X-Workflow-Tenant-Id header, then STUDIO_TENANT_SLUG.
    """
    for candidate in (
        (override or "").strip() or None,
        (settings.STUDIO_TENANT_SLUG or "").strip() or None,
    ):
        if candidate:
            return candidate
    return TenantSlug.T3RA


@router.post(
    "/email",
    summary="Email webhook",
    responses={
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def webhook_email(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(unipile_webhook_bearer),
    ],
):
    try:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or credentials.credentials != settings.UNIPILE_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")
        payload = await request.json()

        try:
            tenant = resolve_unipile_tenant(payload=payload)
        except TenantResolutionError as e:
            return {"message": f"invalid webhook: {str(e)}"}

        if tenant is None:
            return {"message": "invalid webhook"}

        if tenant.tenant_slug == TenantSlug.GELITA:
            gelita_inbound_email_service = GelitaInboundEmailService()
            return await gelita_inbound_email_service.handle(payload=payload, tenant=tenant)
        if tenant.tenant_slug == TenantSlug.T3RA:
            t3ra_inbound_email_service = T3raInboundEmailService()
            return await t3ra_inbound_email_service.handle(payload=payload, tenant=tenant)

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
    "/turvo",
    summary="Turvo webhook",
    responses={
        400: {"description": "Bad request"},
        500: {"description": "Internal server error"},
    },
)
async def listen_turvo_status(
    request: Request,
    x_workflow_tenant_id: Annotated[
        str | None,
        Header(
            alias="X-Workflow-Tenant-Id",
            description="Optional tenant identifier.",
        ),
    ] = None,
) -> Response:
    try:
        body: dict[str, Any] = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON") from e

    override = x_workflow_tenant_id
    workflow_tenant = _resolve_workflow_tenant_id(override)
    payload = map_turvo_status_webhook_to_payload(body)
    if payload is None or not payload.get("shipment_id"):
        logger.info("Turvo webhook skipped: status key is not 2116 or shipment/load id missing")
        return Response(status_code=status.HTTP_200_OK)

    external_shipment_number = str(payload.get("shipment_id") or "").strip()
    lifecycle_shipment_uuid: str | None = None
    tenant_uuid = resolve_graph_tenant_to_uuid(workflow_tenant)
    if tenant_uuid and external_shipment_number:
        shipments_service = ShipmentsService()
        shipments_row = shipments_service.get_by_shipment_number(
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
        communications_service = CommunicationsService()
        thread = communications_service.resolve_thread_for_lifecycle(
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
        pod_lifecycle_ingress_service = PodLifecycleIngressService()
        duplicate = pod_lifecycle_ingress_service.check_route_completed_duplicate(
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
        logger.info("Turvo webhook queued task_id=%s", task.id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"execution_id": execution_id},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Turvo webhook queueing failed")
        raise HTTPException(status_code=500, detail="Internal error") from e
