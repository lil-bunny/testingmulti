"""T3RA Unipile ingress: classify ratecon / pod_lifecycle and enqueue workflows."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.t3ra.email_classification import (
    T3raInboundEmailClassification,
    classify_t3ra_inbound_email,
)
from app.domain.unipile_email import extract_recipient_emails
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.models.tenants import TenantSlug
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.pod_lifecycle_ingress_service import (
    POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS,
    PodLifecycleIngressService,
)
from app.services.t3ra.driver_details_email_ingress import DriverDetailsEmailIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)


def enqueue_t3ra_workflow(
    *,
    workflow_name: str,
    workflow_payload: dict[str, Any],
    communication_id: str | None,
    event_type: str,
) -> IngressResult:
    """Build Celery payload and enqueue a T3RA workflow from L2 ingress."""
    enriched_workflow_payload = dict(workflow_payload)
    enriched_workflow_payload["event_type"] = event_type
    if communication_id:
        enriched_workflow_payload["communication_id"] = communication_id

    execution_id = str(uuid.uuid4())
    enriched_workflow_payload["execution_id"] = execution_id

    celery_task = run_workflow_async.apply_async(
        kwargs={
            "tenant_slug": TenantSlug.T3RA,
            "workflow_name": workflow_name,
            "payload": enriched_workflow_payload,
        }
    )
    logger.info(
        "t3ra unipile queued task_id=%s execution_id=%s workflow_name=%s",
        celery_task.id,
        execution_id,
        workflow_name,
    )
    return IngressResult(
        outcome="enqueued",
        event_type=event_type,
        execution_ids=(execution_id,),
    )


class T3raEmailIngressService:
    """
    T3RA L2 ingress: classify inbound mail and enqueue the matching workflow.

    Priority when multiple rules could apply: POD lifecycle → driver-details reply → ratecon.
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
        Run T3RA classification and return the first matching ingress outcome.

        ``communication_id`` is passed through to workflow payloads; comm row is created upstream.
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
            return self._enqueue_ratecon(
                payload=payload,
                email_classification=email_classification,
                communication_id=communication_id,
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
        POD ``email_received`` path: Turvo guards, attachment import, then workflow enqueue.

        Returns ``None`` when shipment status is invalid so ``process()`` can fall through.
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

        data_import_id = await process_email_webhook_attachment_import(
            payload=payload,
            workflow_name="pod_lifecycle",
            data_import_tenant_id=tenant.tenant_uuid,
            data_import_data_type=DataImportDataType.LOAD_TENDER,
            ingest_source_type=DataImportSourceType.EMAIL,
        )
        if data_import_id:
            workflow_payload["data_import_id"] = data_import_id

        return enqueue_t3ra_workflow(
            workflow_name="pod_lifecycle",
            workflow_payload=workflow_payload,
            communication_id=communication_id,
            event_type="email_received",
        )

    @staticmethod
    def _enqueue_ratecon(
        *,
        payload: dict[str, Any],
        email_classification: T3raInboundEmailClassification,
        communication_id: str | None,
    ) -> IngressResult:
        """
        Enqueue ratecon workflow from classification output.

        Classification already resolved load id and workflow name; this method only builds
        the Celery payload and assigns a fresh ``execution_id``.
        """
        workflow_payload = {
            **payload,
            **email_classification.to_ratecon_enqueue_payload(),
        }
        return enqueue_t3ra_workflow(
            workflow_name="ratecon",
            workflow_payload=workflow_payload,
            communication_id=communication_id,
            event_type="email_received",
        )
