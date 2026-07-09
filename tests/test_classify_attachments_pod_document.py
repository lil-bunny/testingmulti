"""Tests for classify_attachments node POD document persistence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState


@patch("app.workflows.nodes.pod.insert_document")
@patch("app.workflows.nodes.pod.PodAttachmentNormalizeService")
def test_classify_attachments_persists_merged_pod_with_source_keys(
    mock_svc_cls: MagicMock,
    mock_insert: MagicMock,
) -> None:
    from app.workflows.nodes.pod import classify_attachments

    mock_svc_cls.return_value.normalize_from_state_data.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
        "pod_merged_local_path": "/tmp/freightx/pod_staging/pod_email_mock/pod_SHIP.pdf",
        "classification_results": [
            {
                "attachment_ref": "pod_attachments/pod_att-1_SHIP.bin",
                "is_valid_document": True,
            }
        ],
        "source_attachment_ids": ["att-1"],
        "rejected": [],
    }
    mock_insert.return_value = {
        "stored": True,
        "id": "doc-1",
        "metadata": {"source_object_keys": ["pod_attachments/merged.pdf"]},
    }

    state = WorkflowState(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={
            "attachment_bytes_by_id": {"att-1": b"%PDF-1.4 x"},
            "pod_attachment_stage_dir": "/tmp/freightx/pod_staging/pod_email_mock",
            "pod_attachment_stage_files": [{"attachment_id": "att-1", "path": "/tmp/freightx/pod_staging/pod_email_mock/att-1.bin"}],
            "shipments_row_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "shipment_id": "SHIP",
        },
    )

    classify_attachments(state)

    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["storage_key"] == "pod_attachments/merged.pdf"
    assert kwargs["metadata"]["source_object_keys"] == ["pod_attachments/merged.pdf"]
    assert state.data["documents_pod"]["id"] == "doc-1"
    assert state.data["pod_object_keys"] == ["pod_attachments/merged.pdf"]
    assert "attachment_bytes_by_id" not in state.data
    assert "get_email_attachments_results" not in state.data
    # Keep stage dir + path-only merged ref for pod_analysis; never store PDF bytes.
    assert state.data["pod_attachment_stage_dir"] == "/tmp/freightx/pod_staging/pod_email_mock"
    assert state.data["pod_merged_local_path"] == (
        "/tmp/freightx/pod_staging/pod_email_mock/pod_SHIP.pdf"
    )
    assert "pod_attachment_stage_files" not in state.data
    assert "pod_merged_pdf_bytes" not in state.data
