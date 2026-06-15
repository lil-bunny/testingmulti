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
from app.services.email_webhook_attachment_ingestion import (
    process_email_webhook_attachment_import,
)
from app.services.pod_lifecycle_ingress_service import PodLifecycleIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_classifier_service import WorkflowClassifierService
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)


class T3raInboundEmailService:
    """L2 classification for T3RA: ratecon vs pod_lifecycle (subject + attachment rules)."""

    def __init__(self) -> None:
        self._communications = CommunicationsService()
        self._pod_lifecycle_ingress = PodLifecycleIngressService()

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
        if not classification:
            logger.info(
                "t3ra unipile: no workflow classified webhook_name=%r",
                payload.get("webhook_name"),
            )
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "no workflow classified"},
            )

        workflow_name = classification.get("workflow_name")
        if workflow_name not in {"ratecon", "pod_lifecycle"}:
            return JSONResponse(
                status_code=status.HTTP_200_OK,
                content={"message": "invalid workflow type"},
            )

        if workflow_name == "ratecon":
            workflow_payload = {
                **payload,
                **classification,
                "event_type": "email_received",
            }
        else:
            data_import_id = await process_email_webhook_attachment_import(
                payload=payload,
                workflow_name=str(workflow_name),
                data_import_tenant_id=tenant.tenant_uuid,
                data_import_data_type=DataImportDataType.LOAD_TENDER,
                ingest_source_type=DataImportSourceType.EMAIL,
            )
            workflow_payload = {**payload, "event_type": "email_received"}
            if data_import_id:
                workflow_payload["data_import_id"] = data_import_id

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

        if communication_id:
            workflow_payload["communication_id"] = communication_id

        execution_id = str(uuid.uuid4())
        workflow_payload["execution_id"] = execution_id

        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": TenantSlug.T3RA,
                "workflow_name": str(workflow_name),
                "payload": workflow_payload,
            }
        )
        logger.info(
            "t3ra unipile queued task_id=%s execution_id=%s workflow_name=%s",
            task.id,
            execution_id,
            workflow_name,
        )
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"message": "success", "execution_id": execution_id},
        )
