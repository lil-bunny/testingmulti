"""Enqueue ``pod_lifecycle`` for ops-uploaded POD PDFs (same graph path as email)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from app.core.logger import get_logger
from app.models.tenants import TenantSlug
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_lifecycle.tms_upload_service import (
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
    source: Literal["upload", "stored"]


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
        pdf_bytes: bytes | None = None,
        filename: str | None = None,
        uploaded_by: str | None = None,
        uploaded_by_user_id: str | None = None,
    ) -> PodManualUploadEnqueueResult:
        resolution = self._staging.resolve_pod_lifecycle(
            tenant_slug=tenant_slug,
            shipment_id=shipment_id,
        )
        if pdf_bytes is not None:
            staged = self._staging.stage_pod_attachment(
                pdf_bytes=pdf_bytes,
                shipment_id=resolution.shipment_number,
                shipments_row_id=resolution.shipments_row_id,
                filename=filename,
            )
            object_key = staged.object_key
            document_id = staged.document_id
            source: Literal["upload", "stored"] = "upload"
        else:
            stored = self._staging.resolve_stored_pod_document(
                shipments_row_id=resolution.shipments_row_id,
            )
            object_key = stored.storage_key
            document_id = stored.document_id
            source = "stored"

        execution_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "event_type": WorkflowRunEventType.MANUAL_POD_UPLOAD.value,
            "workflow_name": POD_LIFECYCLE_WORKFLOW,
            "shipment_id": resolution.shipment_number,
            "shipments_row_id": resolution.shipments_row_id,
            "workflow_lifecycle_id": resolution.workflow_lifecycle_id,
            "pod_object_keys": [object_key],
            "execution_id": execution_id,
            "manual_pod_upload_source": source,
        }
        if uploaded_by:
            payload["uploaded_by"] = uploaded_by
        if uploaded_by_user_id:
            payload["uploaded_by_user_id"] = uploaded_by_user_id
        if document_id:
            payload["manual_pod_document_id"] = document_id

        from app.services.worker_queue_routing import apply_async_on_work_queue
        from app.tasks.workflows import run_workflow_async

        task = apply_async_on_work_queue(
            run_workflow_async,
            tenant_slug=TenantSlug.T3RA,
            kwargs={
                "tenant_slug": TenantSlug.T3RA,
                "workflow_name": POD_LIFECYCLE_WORKFLOW,
                "payload": payload,
            },
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
            object_key=object_key,
            document_id=document_id,
            celery_task_id=task.id,
            source=source,
        )


__all__ = (
    "PodLifecycleNotFoundError",
    "PodManualUploadEnqueueResult",
    "PodManualUploadIngressService",
)
