"""Tests for classify_attachments node POD document persistence."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState


@patch("app.workflows.nodes.pod.insert_document")
@patch("app.workflows.nodes.pod.get_normalized_attachments")
def test_classify_attachments_persists_single_pod_with_source_keys(
    mock_normalize: MagicMock,
    mock_insert: MagicMock,
) -> None:
    from app.workflows.nodes.pod import classify_attachments

    mock_normalize.side_effect = lambda state: state
    mock_insert.return_value = {
        "stored": True,
        "id": "doc-1",
        "metadata": {"source_object_keys": ["pod_attachments/a.pdf"]},
    }

    state = WorkflowState(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={
            "pod_object_keys": ["pod_attachments/a.pdf"],
            "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
            "shipments_row_id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        },
    )

    classify_attachments(state)

    mock_insert.assert_called_once()
    kwargs = mock_insert.call_args.kwargs
    assert kwargs["metadata"] == {"source_object_keys": ["pod_attachments/a.pdf"]}
    assert state.data["documents_pod"]["id"] == "doc-1"
