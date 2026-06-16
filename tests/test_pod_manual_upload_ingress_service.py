"""PodManualUploadIngressService unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.pod_manual_upload_ingress_service import PodManualUploadIngressService
from app.services.pod_tms_upload_service import (
    PodAttachmentStageResult,
    PodLifecycleNotFoundError,
    PodLifecycleResolution,
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

    celery_task = MagicMock(id="celery-task-1")
    with patch(
        "app.tasks.workflows.run_workflow_async.apply_async",
        return_value=celery_task,
    ) as apply_async:
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

    apply_async.assert_called_once()
    kwargs = apply_async.call_args.kwargs["kwargs"]
    payload = kwargs["payload"]
    assert payload["event_type"] == WorkflowRunEventType.MANUAL_POD_UPLOAD.value
    assert payload["shipment_id"] == "1000324895"
    assert payload["shipments_row_id"] == _SHIPMENTS_ROW_UUID
    assert payload["pod_object_keys"] == ["pod_attachments/manual.pdf"]
    assert payload["uploaded_by"] == "ana.gelita.test@freightx.ai"
    assert kwargs["workflow_name"] == "pod_lifecycle"


def test_enqueue_propagates_missing_lifecycle():
    staging = MagicMock()
    staging.resolve_pod_lifecycle.side_effect = PodLifecycleNotFoundError("pod_lifecycle not found")

    with pytest.raises(PodLifecycleNotFoundError):
        PodManualUploadIngressService(staging_service=staging).enqueue(
            tenant_slug="t3ra",
            shipment_id=_SHIPMENTS_ROW_UUID,
            pdf_bytes=_MIN_PDF,
        )
