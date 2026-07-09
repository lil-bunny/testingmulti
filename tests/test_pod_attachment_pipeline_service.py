"""Tests for pre-graph ``PodAttachmentPipelineService``."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.pod_lifecycle.attachment_pipeline_service import (
    PodAttachmentPipelineService,
)
from app.services.pod_lifecycle.ingress_service import POD_EMAIL_SKIP_INVALID_ATTACHMENT


@pytest.mark.asyncio
async def test_run_for_email_skips_when_no_attachments():
    svc = PodAttachmentPipelineService(normalizer=MagicMock())
    result = await svc.run_for_email_payload(payload={"shipment_id": "S1"})
    assert result.success is False
    assert result.skip_reason == "no_attachments"


@pytest.mark.asyncio
async def test_run_for_email_persists_merged_pod(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    normalizer = MagicMock()
    normalizer.normalize_from_bytes.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "pod_attachments/pod_S1.pdf",
        "pod_merged_local_path": str(tmp_path / "pod_S1.pdf"),
        "source_attachments_cleanup": {
            "valid_source": [{"attachment_ref": "pod_attachments/pod_att1_S1.bin"}],
            "rejected": [],
        },
        "rejected": [],
    }
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.fetch_email_attachment_bytes_with_retry",
        lambda **kwargs: b"%PDF-1.4 x",
    )
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.insert_document",
        lambda *a, **k: {"stored": True, "id": "doc-1", "storage_key": k.get("storage_key") or a[1]},
    )
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.resolve_pod_sender_account_id",
        lambda payload: "acct-1",
    )

    svc = PodAttachmentPipelineService(normalizer=normalizer)
    result = await svc.run_for_email_payload(
        payload={
            "shipment_id": "S1",
            "shipments_row_id": "row-1",
            "email_id": "email-1",
            "attachments": [{"id": "att-1"}],
            "execution_id": "exec-1",
        }
    )

    assert result.success is True
    assert result.state_patch is not None
    assert result.state_patch["pod_merged_pdf_object_key"] == "pod_attachments/pod_S1.pdf"
    assert result.state_patch["documents_pod"]["stored"] is True
    assert result.state_patch["has_attachments"] is True
    assert result.state_patch["pod_source_object_keys"] == [
        "pod_attachments/pod_att1_S1.bin"
    ]
    normalizer.normalize_from_bytes.assert_called_once()
    _, kwargs = normalizer.normalize_from_bytes.call_args
    assert kwargs["trace_metadata"]["execution_id"] == "exec-1"
    assert kwargs["trace_metadata"]["shipment_id"] == "S1"
    assert kwargs["trace_metadata"]["workflow_name"] == "pod_lifecycle"
    assert kwargs["trace_metadata"]["step_key"] == "pod_attachment_classifier"
    assert kwargs["trace_metadata"]["classify_context"] == "attachment_pipeline"


def test_classifier_trace_metadata_minimal_fields():
    meta = PodAttachmentPipelineService._classifier_trace_metadata(
        {
            "execution_id": "exec-9",
            "workflow_lifecycle_id": "wl-9",
            "tenant_id": "tid",
            "tenant_slug": "t3ra",
            "shipment_id": "1001",
            "email_id": "should-not-appear",
            "communication_id": "should-not-appear",
        }
    )
    assert meta == {
        "workflow_name": "pod_lifecycle",
        "step_key": "pod_attachment_classifier",
        "classify_context": "attachment_pipeline",
        "execution_id": "exec-9",
        "workflow_lifecycle_id": "wl-9",
        "tenant_id": "tid",
        "tenant_slug": "t3ra",
        "shipment_id": "1001",
    }


@pytest.mark.asyncio
async def test_run_for_email_invalid_document_skips(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    normalizer = MagicMock()
    normalizer.normalize_from_bytes.return_value = {
        "success": False,
        "error": "No valid document",
        "rejected": [{"reason": "truck photo"}],
    }
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.fetch_email_attachment_bytes_with_retry",
        lambda **kwargs: b"not-pdf",
    )
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.resolve_pod_sender_account_id",
        lambda payload: "acct-1",
    )

    svc = PodAttachmentPipelineService(normalizer=normalizer)
    result = await svc.run_for_email_payload(
        payload={
            "shipment_id": "S1",
            "email_id": "email-1",
            "attachments": [{"id": "att-bad"}],
        }
    )

    assert result.success is False
    assert result.skip_reason == POD_EMAIL_SKIP_INVALID_ATTACHMENT


def test_run_for_object_keys_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    normalizer = MagicMock()
    normalizer.normalize.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "pod_attachments/pod_S1.pdf",
        "source_attachments_cleanup": {
            "valid_source": [{"attachment_ref": "pod_attachments/pod_manual_S1.pdf"}],
            "rejected": [],
        },
    }
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.insert_document",
        lambda *a, **k: {"stored": True, "id": "doc-2"},
    )

    svc = PodAttachmentPipelineService(normalizer=normalizer)
    result = svc.run_for_object_keys(
        pod_object_keys=["pod_attachments/pod_manual_S1.pdf"],
        shipment_id="S1",
        shipments_row_id="row-1",
        stage_token="exec-manual",
    )

    assert result.success is True
    assert result.state_patch["documents_pod"]["id"] == "doc-2"
    normalizer.normalize.assert_called_once()
    _, kwargs = normalizer.normalize.call_args
    assert kwargs["trace_metadata"]["execution_id"] == "exec-manual"
    assert kwargs["trace_metadata"]["shipment_id"] == "S1"
    assert kwargs["trace_metadata"]["classify_context"] == "attachment_pipeline"
