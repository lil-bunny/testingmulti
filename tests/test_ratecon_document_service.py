"""Unit tests for ``RateconDocumentService`` upload + documents persistence."""

from __future__ import annotations

from unittest.mock import patch

from app.services.ratecon_document_service import RateconDocumentService


def test_upload_skips_when_no_attachments() -> None:
    out = RateconDocumentService().upload_email_attachments({})
    assert out["skipped"] is True
    assert out["reason"] == "no_attachments"


def test_upload_skips_when_missing_email_id() -> None:
    out = RateconDocumentService().upload_email_attachments(
        {"attachments": [{"id": "a1"}]}
    )
    assert out["skipped"] is True
    assert out["reason"] == "missing_email_id"


@patch(
    "app.services.ratecon_document_service.resolve_shipment_id",
    return_value=None,
)
def test_upload_skips_when_missing_shipment_id(_mock_shipment) -> None:
    out = RateconDocumentService().upload_email_attachments(
        {"attachments": [{"id": "a1"}], "email_id": "e1"}
    )
    assert out["skipped"] is True
    assert out["reason"] == "missing_shipment_id"


@patch("app.services.ratecon_document_service.insert_document")
@patch(
    "app.services.ratecon_document_service.bucket.upload_file",
    return_value={"success": True, "object_key": "ratecon_attachments/ratecon_SHIP-1.pdf"},
)
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
@patch(
    "app.services.ratecon_document_service.resolve_shipment_id",
    return_value="SHIP-1",
)
def test_upload_persists_documents_row(
    _mock_shipment,
    _mock_row,
    _mock_fetch,
    _mock_type,
    _mock_upload,
    mock_insert,
) -> None:
    mock_insert.return_value = {"stored": True, "id": "doc-1"}
    out = RateconDocumentService().upload_email_attachments(
        {
            "attachments": [{"id": "att-1", "name": "rc.pdf"}],
            "email_id": "email-1",
            "shipments_row_id": "11111111-1111-4111-8111-111111111111",
        }
    )
    assert out["all_succeeded"] is True
    assert out["ratecon_object_keys"] == ["ratecon_attachments/ratecon_SHIP-1.pdf"]
    mock_insert.assert_called_once()
    args = mock_insert.call_args.args
    kwargs = mock_insert.call_args.kwargs
    assert args[1] == "ratecon_attachments/ratecon_SHIP-1.pdf"
    assert kwargs["shipments_row_id"] == "11111111-1111-4111-8111-111111111111"
    assert out["results"][0]["document_persist"]["stored"] is True


@patch(
    "app.services.ratecon_document_service.bucket.upload_file",
    return_value={"success": True, "object_key": "ratecon_attachments/ratecon_SHIP-1.pdf"},
)
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
    return_value=None,
)
def test_upload_skips_document_persist_when_shipments_row_id_missing(
    _mock_row,
    _mock_fetch,
    _mock_type,
    _mock_upload,
) -> None:
    out = RateconDocumentService().upload_email_attachments(
        {
            "attachments": [{"id": "att-1"}],
            "email_id": "email-1",
            "shipment_id": "SHIP-1",
        }
    )
    assert out["all_succeeded"] is True
    assert out["results"][0]["success"] is True
    assert out["results"][0]["document_persist"]["stored"] is False
    assert out["results"][0]["document_persist"]["reason"] == "missing_shipments_row_id"
