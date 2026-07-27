"""Unit tests for ``RateconDocumentService`` (no S3)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.ratecon_document_service import RateconDocumentService


def test_cache_skips_when_no_attachments() -> None:
    out = RateconDocumentService().cache_from_email_attachments({})
    assert out["skipped"] is True
    assert out["reason"] == "no_attachments"


def test_cache_skips_when_missing_email_id() -> None:
    out = RateconDocumentService().cache_from_email_attachments(
        {"attachments": [{"id": "a1"}]}
    )
    assert out["skipped"] is True
    assert out["reason"] == "missing_email_id"


@patch(
    "app.services.ratecon_document_service.resolve_shipments_row_id_for_db",
    return_value=None,
)
def test_cache_skips_when_missing_shipments_row_id(_mock_row) -> None:
    out = RateconDocumentService().cache_from_email_attachments(
        {"attachments": [{"id": "a1"}], "email_id": "e1"}
    )
    assert out["skipped"] is True
    assert out["reason"] == "missing_shipments_row_id"


@patch("app.services.ratecon_document_service.upsert_document_analysis")
@patch("app.services.ratecon_document_service.pdf_page_count", return_value=4)
@patch(
    "app.services.ratecon_document_service.detect_attachment_bytes_type",
    return_value=("pdf", "application/pdf"),
)
@patch(
    "app.services.ratecon_document_service.get_email_attachments",
    return_value=b"%PDF-1.4 stub",
)
@patch(
    "app.services.ratecon_document_service.resolve_shipments_row_id_for_db",
    return_value="11111111-1111-4111-8111-111111111111",
)
def test_cache_upserts_page_count(
    _mock_row, _mock_fetch, _mock_type, _mock_count, mock_upsert
) -> None:
    mock_upsert.return_value = {"stored": True, "id": "da-1"}
    out = RateconDocumentService().cache_from_email_attachments(
        {
            "attachments": [{"id": "att-1", "name": "rc.pdf"}],
            "email_id": "email-1",
            "shipments_row_id": "11111111-1111-4111-8111-111111111111",
        }
    )
    assert out["success"] is True
    assert out["page_count"] == 4
    mock_upsert.assert_called_once()
    kwargs = mock_upsert.call_args.kwargs
    assert kwargs["page_count"] == 4
    assert kwargs["results"] == {"source": "ratecon_page_count"}


@patch("app.services.ratecon_document_service.upsert_document_analysis")
@patch(
    "app.services.ratecon_document_service.detect_attachment_bytes_type",
    return_value=("jpg", "image/jpeg"),
)
@patch(
    "app.services.ratecon_document_service.get_email_attachments",
    return_value=b"\xff\xd8\xff",
)
@patch(
    "app.services.ratecon_document_service.resolve_shipments_row_id_for_db",
    return_value="11111111-1111-4111-8111-111111111111",
)
def test_cache_fails_when_no_pdf(
    _mock_row, _mock_fetch, _mock_type, mock_upsert
) -> None:
    out = RateconDocumentService().cache_from_email_attachments(
        {"attachments": [{"id": "att-1"}], "email_id": "email-1"}
    )
    assert out["success"] is False
    assert out["reason"] == "no_pdf_page_count"
    mock_upsert.assert_not_called()
