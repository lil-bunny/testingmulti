"""pod_analysis prefers worker-local merged PDF path; falls back to S3."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.tools.pod import pod_analysis


def _extract_ok(path, **_kwargs):
    return (
        [{"extracted_data": {"x": 1}, "error": None}],
        {"delivery_confirmed": True},
        [],
        [],
        {"reconciled": {}},
    )


@patch("app.tools.pod.extract_pod_from_pdf_path", side_effect=_extract_ok)
@patch("app.tools.pod.bucket")
@patch("app.tools.pod.resolve_merged_pod_object_key")
def test_pod_analysis_prefers_local_merged_path(
    mock_resolve: MagicMock,
    mock_bucket: MagicMock,
    mock_extract: MagicMock,
    tmp_path,
) -> None:
    merged = tmp_path / "pod_SHIP.pdf"
    merged.write_bytes(b"%PDF-1.4 local-merged")
    mock_resolve.return_value = (
        "pod_attachments/merged.pdf",
        {"source": "state"},
    )

    out = pod_analysis(
        {
            "shipment_id": "SHIP",
            "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
            "pod_merged_local_path": str(merged),
            "documents_pod": {"id": "doc-1"},
        }
    )

    mock_bucket.download_object_bytes.assert_not_called()
    mock_extract.assert_called_once()
    assert mock_extract.call_args.args[0] == str(merged)
    assert out["success"] is True
    assert out["findings"]["metadata"]["pod_bytes_source"] == "local_stage"
    assert merged.is_file()


@patch("app.tools.pod.extract_pod_from_pdf_path", side_effect=_extract_ok)
@patch("app.tools.pod.bucket")
@patch("app.tools.pod.resolve_merged_pod_object_key")
def test_pod_analysis_falls_back_to_s3_when_local_missing(
    mock_resolve: MagicMock,
    mock_bucket: MagicMock,
    mock_extract: MagicMock,
    tmp_path,
) -> None:
    missing = tmp_path / "gone.pdf"
    mock_resolve.return_value = (
        "pod_attachments/merged.pdf",
        {"source": "state"},
    )
    mock_bucket.download_object_bytes.return_value = {
        "success": True,
        "body": b"%PDF-1.4 from-s3",
    }

    out = pod_analysis(
        {
            "shipment_id": "SHIP",
            "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
            "pod_merged_local_path": str(missing),
            "documents_pod": {"id": "doc-1"},
        }
    )

    mock_bucket.download_object_bytes.assert_called_once_with(
        "pod_attachments/merged.pdf"
    )
    assert out["success"] is True
    assert out["findings"]["metadata"]["pod_bytes_source"] == "s3"
    # Tool must not put PDF bytes into the input/state dict.
    assert "pod_merged_pdf_bytes" not in out
