"""Enqueue ``pod_lifecycle`` for ops-uploaded POD PDFs (same graph path as email)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.models.tenants import TenantSlug
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_tms_upload_service import (
    POD_LIFECYCLE_WORKFLOW,
    PodLifecycleNotFoundError,
    PodTmsUploadService,
)
logger = get_logger(__name__)


@dataclass(frozen=True)
class PodManualUploadEnqueueResult:
    execution_id: str
    workflow_lifecycle_id: str
    shipment_id: str
    object_key: str
    document_id: str | None
    celery_task_id: str | None


class PodManualUploadIngressService:
    def __init__(
        self,
        *,
        staging_service: PodTmsUploadService | None = None,
    ) -> None:
        self._staging = staging_service or PodTmsUploadService()

    def enqueue(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        pdf_bytes: bytes,
        filename: str | None = None,
        uploaded_by: str | None = None,
        uploaded_by_user_id: str | None = None,
    ) -> PodManualUploadEnqueueResult:
        resolution = self._staging.resolve_pod_lifecycle(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
        )
        staged = self._staging.stage_pod_attachment(
            pdf_bytes=pdf_bytes,
            shipment_id=resolution.shipment_number,
            shipments_row_id=resolution.shipments_row_id,
            filename=filename,
        )

        execution_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "event_type": WorkflowRunEventType.MANUAL_POD_UPLOAD.value,
            "workflow_name": POD_LIFECYCLE_WORKFLOW,
            "shipment_id": resolution.shipment_number,
            "shipments_row_id": resolution.shipments_row_id,
            "workflow_lifecycle_id": resolution.workflow_lifecycle_id,
            "pod_object_keys": [staged.object_key],
            "execution_id": execution_id,
        }
        if uploaded_by:
            payload["uploaded_by"] = uploaded_by
        if uploaded_by_user_id:
            payload["uploaded_by_user_id"] = uploaded_by_user_id
        if staged.document_id:
            payload["manual_pod_document_id"] = staged.document_id

        from app.tasks.workflows import run_workflow_async

        task = run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": TenantSlug.T3RA,
                "workflow_name": POD_LIFECYCLE_WORKFLOW,
                "payload": payload,
            }
        )
        logger.info(
            "pod_manual_upload queued task_id=%s execution_id=%s lifecycle_id=%s shipment_id=%s",
            task.id,
            execution_id,
            resolution.workflow_lifecycle_id,
            resolution.shipment_number,
        )
        return PodManualUploadEnqueueResult(
            execution_id=execution_id,
            workflow_lifecycle_id=resolution.workflow_lifecycle_id,
            shipment_id=resolution.shipments_row_id,
            object_key=staged.object_key,
            document_id=staged.document_id,
            celery_task_id=task.id,
        )


__all__ = (
    "PodLifecycleNotFoundError",
    "PodManualUploadEnqueueResult",
    "PodManualUploadIngressService",
)
