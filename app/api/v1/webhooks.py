"""v1 inbound webhook endpoints (Unipile email, Turvo status)."""

import uuid
from typing import Annotated, Any, Optional

from app.exceptions import TenantResolutionError
from fastapi import APIRouter, Header, HTTPException, Request, Security, status
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.security import turvo_webhook_bearer, unipile_webhook_bearer

from app.core.config import settings
from app.core.logger import get_logger
from app.models.tenants import TenantSlug
from app.integrations.turvo.webhook_mapping import (
    TENDERED_STATUS_CODE_KEY,
    map_turvo_status_webhook,
    map_turvo_status_webhook_to_payload,
)
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.communications.service import CommunicationsService
from app.services.appointment_scheduling.ingress_service import AppointmentSchedulingIngressService
from app.services.pod_lifecycle.ingress_service import (
    ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
    ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
    PodLifecycleIngressService,
)
from app.domain.email_ingress_heavy_work import payload_requires_heavy_ingress_work
from app.domain.unipile_email import extract_email_id_or_none
from app.services.email_ingress_work_queue_serializer_service import (
    EmailIngressWorkQueueSerializerService,
)
from app.services.inbound_webhook_enqueue import accept_inbound_unipile_email
from app.services.shipments_service import ShipmentsService
from app.services.unipile_tenant_resolution import resolve_unipile_tenant
from app.integrations.turvo.workflow_cancel import shipment_tendered_trigger_from_turvo
from app.services.workflow_lifecycle_cancel_orchestrator import (
    WorkflowLifecycleCancelOrchestrator,
)
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService

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
    """
    Unipile email webhook: auth, tenant resolve, then Ingress accept on-request.

    Heavy deliveries (Edge Heavy-Work Gate match, e.g. sheet attachments) admit to
    the Pre-Lifecycle Work Queue instead of running Ingress inline; the worker
    classifies and runs Heavy Ingress Work off the request path. Everything else
    keeps today's cheap inline Ingress path.

    Outcomes: ``202`` when work is accepted, buffered, or queued for background
    processing; ``200`` when the delivery was already claimed, skipped, or unmatched.
    """
    try:
        # Guard: reject before parsing body on bad credentials.
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

        email_id = extract_email_id_or_none(payload)
        if not email_id:
            return {"message": "invalid webhook"}

        if payload_requires_heavy_ingress_work(payload):
            email_ingress_work_queue_serializer_service = EmailIngressWorkQueueSerializerService()
            email_ingress_work_queue_serializer_service.admit(
                email_id=email_id,
                tenant_uuid=tenant.tenant_uuid,
                tenant_slug=tenant.tenant_slug,
                payload=payload,
            )
            content = {
                "accepted": True,
                "email_id": email_id,
                "status": "queued_for_processing",
            }
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=content)

        email_id, queue_status = await accept_inbound_unipile_email(
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            payload=payload,
        )
        content = {
            "accepted": True,
            "email_id": email_id,
            "status": queue_status,
        }
        if queue_status in ("accepted", "buffered"):
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=content)
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)
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
        401: {"description": "Unauthorized"},
        500: {"description": "Internal server error"},
    },
)
async def listen_turvo_status(
    request: Request,
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Security(turvo_webhook_bearer),
    ],
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

    secret = (settings.TURVO_WEBHOOK_SECRET or "").strip()
    if secret:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or credentials.credentials != secret
        ):
            raise HTTPException(status_code=401, detail="Unauthorized")

    override = x_workflow_tenant_id
    workflow_tenant = _resolve_workflow_tenant_id(override)

    scheduling_result = await AppointmentSchedulingIngressService().handle_shipment_update(
        body,
        workflow_tenant,
    )
    if scheduling_result.handled:
        if scheduling_result.enqueued:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"execution_id": scheduling_result.execution_id},
            )
        content: dict[str, Any] = {"skipped": scheduling_result.skip_reason}
        return JSONResponse(status_code=status.HTTP_200_OK, content=content)

    event = map_turvo_status_webhook(body)
    if event is None:
        logger.info("Turvo webhook skipped: unsupported status or shipment/load id missing")
        return Response(status_code=status.HTTP_200_OK)

    if event.status_key == TENDERED_STATUS_CODE_KEY:
        if not event.shipment_id:
            logger.info("Turvo tendered webhook skipped: shipment id missing")
            return Response(status_code=status.HTTP_200_OK)
        trigger = shipment_tendered_trigger_from_turvo(
            tenant_id=workflow_tenant,
            tenant_slug=workflow_tenant,
            event=event,
        )
        results = WorkflowLifecycleCancelOrchestrator().cancel_for_trigger(trigger)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=WorkflowLifecycleCancelOrchestrator.to_api_content(results),
        )

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

        convoy_gate = await pod_lifecycle_ingress_service.check_route_completed_convoy_gate(
            tenant_slug=workflow_tenant,
            payload=payload,
        )
        if convoy_gate.skip:
            logger.info(
                "Turvo webhook skipped: convoy load shipment_number=%s",
                external_shipment_number,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "skipped": ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
                    "shipment_id": external_shipment_number,
                },
            )

        pod_gate = await pod_lifecycle_ingress_service.check_route_completed_pod_gate(
            tenant_slug=workflow_tenant,
            payload=payload,
        )
        if pod_gate.skip:
            logger.info(
                "Turvo webhook skipped: POD already exists shipment_number=%s",
                external_shipment_number,
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={
                    "skipped": ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
                    "shipment_id": external_shipment_number,
                },
            )

    try:
        execution_id = str(uuid.uuid4())
        queued_payload = {**payload, "execution_id": execution_id}
        if lifecycle_shipment_uuid:
            queued_payload["shipments_row_id"] = lifecycle_shipment_uuid

        tenant_id_for_resolve = tenant_uuid or workflow_tenant
        lifecycle_run_serializer_service = LifecycleRunSerializerService()
        result = lifecycle_run_serializer_service.resolve_then_enqueue(
            tenant_id=str(tenant_id_for_resolve),
            tenant_slug=workflow_tenant,
            workflow_name=LISTEN_TURVO_WORKFLOW_NAME,
            payload=queued_payload,
        )
        logger.info(
            "Turvo webhook serialize status=%s celery_task_id=%s execution_id=%s "
            "lifecycle_id=%s",
            result.status,
            result.celery_task_id,
            execution_id,
            result.lifecycle_id,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "execution_id": execution_id,
                "status": result.status,
                "workflow_lifecycle_id": result.lifecycle_id,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Turvo webhook queueing failed")
        raise HTTPException(status_code=500, detail="Internal error") from e
