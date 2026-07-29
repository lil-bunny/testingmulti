"""Tests for ``PodAttachmentPipelineService`` assess + merge/upload."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.pod_lifecycle.guards import ATTACHMENT_CLASSIFIER_FAILED
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
async def test_run_for_email_assess_stages_without_s3_merge(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    staged = tmp_path / "sources" / "001_att1.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"%PDF-1.4 x")
    normalizer = MagicMock()
    normalizer.normalize_from_bytes_async = AsyncMock(
        return_value={
            "success": True,
            "assess_only": True,
            "pod_merged_pdf_object_key": None,
            "pod_merge_source_paths": [str(staged)],
            "pod_vision_image_paths": [],
            "source_attachments_cleanup": {
                "valid_source": [{"attachment_ref": "pod_attachments/pod_att1_S1.bin"}],
                "rejected": [],
            },
            "rejected": [],
        }
    )
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.fetch_email_attachment_bytes_with_retry",
        lambda **kwargs: b"%PDF-1.4 x",
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
    assert "pod_merged_pdf_object_key" not in result.state_patch
    assert "documents_pod" not in result.state_patch
    assert result.state_patch["pod_merge_source_paths"] == [str(staged)]
    assert result.state_patch["has_attachments"] is True
    _, kwargs = normalizer.normalize_from_bytes_async.call_args
    assert kwargs["upload_merged"] is False
    assert kwargs["trace_metadata"]["execution_id"] == "exec-1"
    assert kwargs["trace_metadata"]["classify_context"] == "attachment_pipeline"


def test_merge_local_then_upload_preferred_persists(monkeypatch, tmp_path):
    source = tmp_path / "001.pdf"
    source.write_bytes(b"%PDF-1.4 x")
    local_merged = tmp_path / "pod_S1.pdf"
    local_merged.write_bytes(b"%PDF-1.4 merged")
    normalizer = MagicMock()
    normalizer.merge_staged_local.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": None,
        "pod_merged_local_path": str(local_merged),
    }
    normalizer.upload_local_pdf.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "pod_attachments/pod_S1.pdf",
        "pod_merged_local_path": str(local_merged),
    }
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.insert_document",
        lambda *a, **k: {
            "stored": True,
            "id": "doc-1",
            "storage_key": k.get("storage_key") or a[1],
        },
    )

    svc = PodAttachmentPipelineService(normalizer=normalizer)
    data = {
        "shipment_id": "S1",
        "shipments_row_id": "row-1",
        "pod_merge_source_paths": [str(source)],
        "pod_attachment_stage_dir": str(tmp_path),
        "attachment_normalization": {
            "success": True,
            "source_attachment_ids": ["att-1"],
            "source_attachments_cleanup": {
                "valid_source": [{"attachment_ref": "pod_attachments/pod_att1_S1.bin"}],
                "rejected": [],
            },
        },
    }
    merged = svc.merge_local_from_state(data)
    assert merged.success is True
    patched = {**data, **(merged.state_patch or {})}
    result = svc.upload_preferred_from_state(patched)

    assert result.success is True
    assert result.state_patch["pod_merged_pdf_object_key"] == "pod_attachments/pod_S1.pdf"
    assert result.state_patch["documents_pod"]["stored"] is True
    normalizer.merge_staged_local.assert_called_once()
    normalizer.upload_local_pdf.assert_called_once()


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
    normalizer.normalize_from_bytes_async = AsyncMock(
        return_value={
            "success": False,
            "error": "No valid document",
            "rejected": [{"reason": "truck photo"}],
        }
    )
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


@pytest.mark.asyncio
async def test_run_for_email_classifier_failed_skips_with_typed_reason(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    normalizer = MagicMock()
    normalizer.normalize_from_bytes_async = AsyncMock(
        return_value={
            "success": False,
            "error": ATTACHMENT_CLASSIFIER_FAILED,
            "rejected": [],
        }
    )
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.fetch_email_attachment_bytes_with_retry",
        lambda **kwargs: b"\x89PNG\r\n\x1a\n" + b"x" * 20,
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
            "attachments": [{"id": "att-llm"}],
        }
    )

    assert result.success is False
    assert result.skip_reason == ATTACHMENT_CLASSIFIER_FAILED


@pytest.mark.asyncio
async def test_run_for_object_keys_assesses(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.services.pod_lifecycle.attachment_pipeline_service.settings.POD_ATTACHMENT_STAGE_ROOT",
        str(tmp_path),
    )
    staged = tmp_path / "sources" / "001_manual.pdf"
    staged.parent.mkdir(parents=True)
    staged.write_bytes(b"%PDF-1.4 x")
    normalizer = MagicMock()
    normalizer.normalize_async = AsyncMock(
        return_value={
            "success": True,
            "assess_only": True,
            "pod_merged_pdf_object_key": None,
            "pod_merge_source_paths": [str(staged)],
            "pod_vision_image_paths": [],
            "source_attachments_cleanup": {
                "valid_source": [{"attachment_ref": "pod_attachments/pod_manual_S1.pdf"}],
                "rejected": [],
            },
        }
    )

    svc = PodAttachmentPipelineService(normalizer=normalizer)
    result = await svc.run_for_object_keys(
        pod_object_keys=["pod_attachments/pod_manual_S1.pdf"],
        shipment_id="S1",
        shipments_row_id="row-1",
        stage_token="exec-manual",
    )

    assert result.success is True
    assert "documents_pod" not in (result.state_patch or {})
    _, kwargs = normalizer.normalize_async.call_args
    assert kwargs["upload_merged"] is False
    assert kwargs["trace_metadata"]["execution_id"] == "exec-manual"
    assert kwargs["trace_metadata"]["classify_context"] == "attachment_pipeline"

