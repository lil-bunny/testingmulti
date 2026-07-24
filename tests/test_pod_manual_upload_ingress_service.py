"""PodManualUploadIngressService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.lifecycle_run_serializer_service import SerializeEnqueueResult
from app.services.pod_lifecycle.manual_upload_ingress_service import PodManualUploadIngressService
from app.services.pod_lifecycle.tms_upload_service import (
    PodAttachmentStageResult,
    PodDocumentNotFoundError,
    PodLifecycleNotFoundError,
    PodLifecycleResolution,
    StoredPodDocument,
)

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_enqueue_stages_and_queues_workflow():
    staging = MagicMock()
    staging.resolve_pod_lifecycle.return_value = PodLifecycleResolution(
        tenant_uuid="tenant-uuid",
        shipment_number="1000324895",
        shipments_row_id=_SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id="wl-1",
    )
    staging.stage_pod_attachment.return_value = PodAttachmentStageResult(
        object_key="pod_attachments/manual.pdf",
        document_id="doc-1",
        attachment_id="manual-abc",
    )

    with patch(
        "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService"
    ) as ser_cls:
        ser_cls.return_value.enqueue.return_value = SerializeEnqueueResult(
            lifecycle_id="wl-1",
            inbox_key="inbox:lifecycle:wl-1",
            status="started",
            celery_task_id="celery-task-1",
            workflow_lifecycle_id="wl-1",
        )
        result = PodManualUploadIngressService(staging_service=staging).enqueue(
            tenant_slug="t3ra",
            shipment_id=_SHIPMENTS_ROW_UUID,
            pdf_bytes=_MIN_PDF,
            filename="pod.pdf",
            uploaded_by="ana.gelita.test@freightx.ai",
        )

    assert result.execution_id
    assert result.workflow_lifecycle_id == "wl-1"
    assert result.shipment_id == _SHIPMENTS_ROW_UUID
    assert result.object_key == "pod_attachments/manual.pdf"
    assert result.celery_task_id == "celery-task-1"
    assert result.source == "upload"

    ser_cls.return_value.enqueue.assert_called_once()
    call_kw = ser_cls.return_value.enqueue.call_args.kwargs
    payload = call_kw["payload"]
    assert payload["event_type"] == WorkflowRunEventType.MANUAL_POD_UPLOAD.value
    assert payload["shipment_id"] == "1000324895"
    assert payload["shipments_row_id"] == _SHIPMENTS_ROW_UUID
    assert payload["pod_object_keys"] == ["pod_attachments/manual.pdf"]
    assert payload["uploaded_by"] == "ana.gelita.test@freightx.ai"
    assert payload["manual_pod_upload_source"] == "upload"
    assert call_kw["workflow_name"] == "pod_lifecycle"

    staging.stage_pod_attachment.assert_called_once()


def test_enqueue_uses_stored_document_without_pdf_bytes():
    staging = MagicMock()
    staging.resolve_pod_lifecycle.return_value = PodLifecycleResolution(
        tenant_uuid="tenant-uuid",
        shipment_number="1000324895",
        shipments_row_id=_SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id="wl-1",
    )
    staging.resolve_stored_pod_document.return_value = StoredPodDocument(
        storage_key="pod_attachments/existing.pdf",
        document_id="doc-stored-1",
    )

    with patch(
        "app.services.lifecycle_run_serializer_service.LifecycleRunSerializerService"
    ) as ser_cls:
        ser_cls.return_value.enqueue.return_value = SerializeEnqueueResult(
            lifecycle_id="wl-1",
            inbox_key="inbox:lifecycle:wl-1",
            status="started",
            celery_task_id="celery-task-2",
            workflow_lifecycle_id="wl-1",
        )
        result = PodManualUploadIngressService(staging_service=staging).enqueue(
            tenant_slug="t3ra",
            shipment_id=_SHIPMENTS_ROW_UUID,
            uploaded_by_user_id="user-1",
        )

    staging.stage_pod_attachment.assert_not_called()
    staging.resolve_stored_pod_document.assert_called_once_with(
        shipments_row_id=_SHIPMENTS_ROW_UUID,
    )
    assert result.object_key == "pod_attachments/existing.pdf"
    assert result.document_id == "doc-stored-1"
    assert result.source == "stored"

    payload = ser_cls.return_value.enqueue.call_args.kwargs["payload"]
    assert payload["pod_object_keys"] == ["pod_attachments/existing.pdf"]
    assert payload["manual_pod_document_id"] == "doc-stored-1"
    assert payload["manual_pod_upload_source"] == "stored"
    assert payload["uploaded_by_user_id"] == "user-1"


def test_enqueue_propagates_missing_stored_document():
    staging = MagicMock()
    staging.resolve_pod_lifecycle.return_value = PodLifecycleResolution(
        tenant_uuid="tenant-uuid",
        shipment_number="1000324895",
        shipments_row_id=_SHIPMENTS_ROW_UUID,
        workflow_lifecycle_id="wl-1",
    )
    staging.resolve_stored_pod_document.side_effect = PodDocumentNotFoundError(
        "No POD document on file for shipment"
    )

    with pytest.raises(PodDocumentNotFoundError):
        PodManualUploadIngressService(staging_service=staging).enqueue(
            tenant_slug="t3ra",
            shipment_id=_SHIPMENTS_ROW_UUID,
        )


def test_enqueue_propagates_missing_lifecycle():
    staging = MagicMock()
    staging.resolve_pod_lifecycle.side_effect = PodLifecycleNotFoundError("pod_lifecycle not found")

    with pytest.raises(PodLifecycleNotFoundError):
        PodManualUploadIngressService(staging_service=staging).enqueue(
            tenant_slug="t3ra",
            shipment_id=_SHIPMENTS_ROW_UUID,
            pdf_bytes=_MIN_PDF,
        )
