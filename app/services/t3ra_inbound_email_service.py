"""T3RA Unipile ingress: classify ratecon / pod_lifecycle and enqueue workflows."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.models.data_import import DataImportDataType, DataImportSourceType
from app.models.tenants import TenantSlug
from app.services.communications.service import CommunicationsService
from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.pod_lifecycle_ingress_service import (
    POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS,
    PodEmailIngressSkipped,
    PodLifecycleIngressService,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.domain.unipile_email import extract_recipient_emails
from app.services.workflow_classifier_service import WorkflowClassifierService
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)


class T3raInboundEmailService:
    """L2 classification for T3RA: ratecon vs pod_lifecycle (subject + attachment rules)."""

    def __init__(self) -> None:
        self._communications = CommunicationsService()
        self._pod_lifecycle_ingress = PodLifecycleIngressService()
        self._driver_assignment_ingress = DriverAssignmentIngressService()

    async def handle(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
    ) -> JSONResponse:
        communication_id = self._communications.record_or_resolve_inbound(
            tenant.tenant_uuid,
            payload,
        )

        classification = WorkflowClassifierService().classify_workflow_type(payload)

        if (
            classification
            and classification.get("workflow_name") == "pod_lifecycle"
        ):
            pod_response = await self._try_enqueue_pod_lifecycle(
                payload=payload,
                tenant=tenant,
                communication_id=communication_id,
            )
            if pod_response is not None:
                return pod_response

        driver_response = self._driver_assignment_ingress.try_driver_details_email_received(
            payload=payload,
            tenant=tenant,
            communication_id=communication_id,
        )
        if driver_response is not None:
            return driver_response

        if classification and classification.get("workflow_name") == "ratecon":
            return self._enqueue_ratecon(
                payload=payload,
                classification=classification,
                communication_id=communication_id,
            )

        logger.info(
            "t3ra unipile: no workflow classified recipients=%r",
            extract_recipient_emails(payload),
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "no workflow classified"},
        )

    async def _try_enqueue_pod_lifecycle(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None,
    ) -> JSONResponse | None:
        workflow_payload = {**payload, "event_type": "email_received"}
        try:
            prepared = await self._pod_lifecycle_ingress.prepare_email_received_payload(
                tenant_id=tenant.tenant_uuid,
                tenant_slug=tenant.tenant_slug,
                payload=workflow_payload,
            )
        except PodEmailIngressSkipped as skip:
            logger.info(
                "t3ra unipile: pod email ingress skipped tenant=%s thread_id=%s "
                "reason=%s shipments_row_id=%s",
                tenant.tenant_uuid,
                payload.get("thread_id"),
                skip.reason,
                skip.shipments_row_id,
            )
            if skip.reason == POD_EMAIL_SKIP_INVALID_SHIPMENT_STATUS:
                return None
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "skipped", "reason": skip.reason},
            )

        workflow_payload = prepared

        if self._pod_lifecycle_ingress.is_duplicate_email_pod_ingest(
            tenant_id=tenant.tenant_uuid,
            payload=workflow_payload,
        ):
            logger.info(
                "t3ra unipile: duplicate email POD skipped tenant=%s thread_id=%s",
                tenant.tenant_uuid,
                payload.get("thread_id"),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "pod already processed"},
            )

        data_import_id = await process_email_webhook_attachment_import(
            payload=payload,
            workflow_name="pod_lifecycle",
            data_import_tenant_id=tenant.tenant_uuid,
            data_import_data_type=DataImportDataType.LOAD_TENDER,
            ingest_source_type=DataImportSourceType.EMAIL,
        )
        if data_import_id:
            workflow_payload["data_import_id"] = data_import_id

        if communication_id:
            workflow_payload["communication_id"] = communication_id

        execution_id = str(uuid.uuid4())
        workflow_payload["execution_id"] = execution_id

        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": TenantSlug.T3RA,
                "workflow_name": "pod_lifecycle",
                "payload": workflow_payload,
            }
        )
        logger.info(
            "t3ra unipile queued task_id=%s execution_id=%s workflow_name=pod_lifecycle",
            task.id,
            execution_id,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id},
        )

    @staticmethod
    def _enqueue_ratecon(
        *,
        payload: dict[str, Any],
        classification: dict[str, Any],
        communication_id: str | None,
    ) -> JSONResponse:
        workflow_payload = {
            **payload,
            **classification,
            "event_type": "email_received",
        }
        if communication_id:
            workflow_payload["communication_id"] = communication_id

        execution_id = str(uuid.uuid4())
        workflow_payload["execution_id"] = execution_id

        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": TenantSlug.T3RA,
                "workflow_name": "ratecon",
                "payload": workflow_payload,
            }
        )
        logger.info(
            "t3ra unipile queued task_id=%s execution_id=%s workflow_name=ratecon",
            task.id,
            execution_id,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id},
        )
