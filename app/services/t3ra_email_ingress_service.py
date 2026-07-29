"""T3RA Unipile ingress: classify ratecon / pod_lifecycle and enqueue workflows."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.t3ra.email_classification import (
    T3raInboundEmailClassification,
    classify_t3ra_inbound_email,
)
from app.domain.unipile_email import extract_recipient_emails
from app.models.tenants import TenantSlug
from app.services.pod_lifecycle.ingress_service import (
    POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS,
    PodLifecycleIngressService,
)
from app.services.t3ra.driver_details_email_ingress import DriverDetailsEmailIngressService

if TYPE_CHECKING:
    from app.services.unipile_tenant_resolution import UnipileTenantContext

logger = get_logger(__name__)


def enqueue_t3ra_workflow(
    *,
    workflow_name: str,
    workflow_payload: dict[str, Any],
    communication_id: str | None,
    event_type: str,
    tenant_id: str | None = None,
) -> IngressResult:
    """
    Resolve lifecycle then serialize-enqueue a T3RA graph start.

    Outcomes: ``enqueued`` when Celery publishes (list length 1); ``buffered``
    when another run is already in flight for that lifecycle.
    """
    from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService

    enriched_workflow_payload = dict(workflow_payload)
    enriched_workflow_payload["event_type"] = event_type
    if communication_id:
        enriched_workflow_payload["communication_id"] = communication_id

    execution_id = str(uuid.uuid4())
    enriched_workflow_payload["execution_id"] = execution_id

    tid = str(tenant_id or enriched_workflow_payload.get("tenant_id") or TenantSlug.T3RA).strip()
    lifecycle_run_serializer_service = LifecycleRunSerializerService()
    result = lifecycle_run_serializer_service.resolve_then_enqueue(
        tenant_id=tid,
        tenant_slug=TenantSlug.T3RA,
        workflow_name=workflow_name,
        payload=enriched_workflow_payload,
    )
    logger.info(
        "t3ra unipile serialize status=%s celery_task_id=%s execution_id=%s "
        "workflow_name=%s lifecycle_id=%s",
        result.status,
        result.celery_task_id,
        execution_id,
        workflow_name,
        result.lifecycle_id,
    )
    return IngressResult(
        outcome="enqueued" if result.status == "started" else "buffered",
        event_type=event_type,
        execution_ids=(execution_id,),
    )


class T3raEmailIngressService:
    """
    Classify inbound T3RA mail and enqueue the matching workflow.

    Priority when multiple rules could apply: POD lifecycle → appointment reply → driver-details reply → ratecon.
    Priority: POD lifecycle → appointment reply → driver-details reply → ratecon. Out-of-order or
    duplicate POD paths return skip (no retry storm).
    """

    def __init__(self) -> None:
        self._pod_lifecycle_ingress = PodLifecycleIngressService()
        self._driver_details_email_ingress = DriverDetailsEmailIngressService()

    async def process(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None,
    ) -> IngressResult:
        """
        Classify inbound mail and return the first matching ingress outcome.

        ``communication_id`` is passed through to workflow payloads; the comm row
        is created in graph task prep when missing.
        """
        email_classification = classify_t3ra_inbound_email(payload)

        if email_classification.workflow_name == "pod_lifecycle":
            pod_lifecycle_result = await self._try_enqueue_pod_lifecycle(
                payload=payload,
                tenant=tenant,
                communication_id=communication_id,
            )
            if pod_lifecycle_result is not None:
                return pod_lifecycle_result

        from app.services.appointment_scheduling.customer_reply_ingress import (
            CustomerReplyIngressService,
        )

        appointment_reply_result = CustomerReplyIngressService().try_customer_reply_received(
            payload=payload,
            tenant=tenant,
            communication_id=communication_id,
        )
        if appointment_reply_result is not None:
            return appointment_reply_result

        driver_details_result = (
            self._driver_details_email_ingress.try_driver_details_email_received(
                payload=payload,
                tenant=tenant,
                communication_id=communication_id,
            )
        )
        if driver_details_result is not None:
            return driver_details_result

        if email_classification.workflow_name == "ratecon":
            return await self._enqueue_ratecon(
                payload=payload,
                email_classification=email_classification,
                communication_id=communication_id,
                tenant=tenant,
            )

        logger.info(
            "t3ra unipile: no workflow classified recipients=%r",
            extract_recipient_emails(payload),
        )
        return IngressResult(outcome="no_match", reason="no workflow classified")

    async def _try_enqueue_pod_lifecycle(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None,
    ) -> IngressResult | None:
        """
        POD ``email_received`` path: Turvo guards then serialize-enqueue.

        Returns ``None`` when shipment status is invalid so ``process()`` can fall
        through to driver-details / ratecon. Attachment import runs in graph prep.
        """
        prepare_result = await self._pod_lifecycle_ingress.prepare_pod_email_received_for_ingress(
            tenant_id=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            payload=payload,
        )

        if prepare_result.skipped:
            logger.info(
                "t3ra unipile: pod email ingress skipped tenant=%s thread_id=%s "
                "reason=%s shipments_row_id=%s",
                tenant.tenant_uuid,
                payload.get("thread_id"),
                prepare_result.skip_reason,
                prepare_result.shipments_row_id,
            )
            if prepare_result.skip_reason == POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS:
                return None
            return IngressResult(
                outcome="skipped",
                reason=prepare_result.skip_reason or "pod ingress skipped",
            )

        workflow_payload = prepare_result.workflow_payload or payload

        if prepare_result.is_duplicate:
            logger.info(
                "t3ra unipile: duplicate email POD skipped tenant=%s thread_id=%s",
                tenant.tenant_uuid,
                payload.get("thread_id"),
            )
            return IngressResult(outcome="skipped", reason="pod already processed")

        # Boundary: attachment import is graph task prep, not Ingress.
        return enqueue_t3ra_workflow(
            workflow_name="pod_lifecycle",
            workflow_payload=workflow_payload,
            communication_id=communication_id,
            event_type="email_received",
            tenant_id=tenant.tenant_uuid,
        )

    async def _enqueue_ratecon(
        self,
        *,
        payload: dict[str, Any],
        email_classification: T3raInboundEmailClassification,
        communication_id: str | None,
        tenant: UnipileTenantContext,
    ) -> IngressResult:
        """
        Ratecon start: Turvo load→shipment upsert, then serialize-enqueue.

        Comms/attachment prep stay on the graph Celery task.
        """
        from app.services.ratecon_ingress_service import RateconIngressService

        workflow_payload = {
            **payload,
            **email_classification.to_ratecon_enqueue_payload(),
        }
        ratecon_ingress_service = RateconIngressService()
        workflow_payload = await ratecon_ingress_service.prepare_payload(
            tenant_id=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            payload=workflow_payload,
        )
        return enqueue_t3ra_workflow(
            workflow_name="ratecon",
            workflow_payload=workflow_payload,
            communication_id=communication_id,
            event_type="email_received",
            tenant_id=tenant.tenant_uuid,
        )
