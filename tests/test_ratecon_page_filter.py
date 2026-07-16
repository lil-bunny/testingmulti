"""Unit tests for rate-confirmation heading match and PDF page filter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import fitz

from app.services.pod_lifecycle.ratecon_page_filter_service import (
    RateconPageFilterService,
)
from app.tools.pdf_text import (
    page_has_rate_confirmation_heading,
)


def _pdf_with_page_texts(texts: list[str]) -> bytes:
    """Build a minimal multi-page PDF. Heading detection is mocked in filter tests."""
    doc = fitz.open()
    try:
        for _ in texts:
            doc.new_page(width=612, height=792)
        return doc.tobytes()
    finally:
        doc.close()


def test_page_has_rate_confirmation_heading_exact_phrase():
    assert page_has_rate_confirmation_heading("Rate confirmation\nShipment ID")
    assert page_has_rate_confirmation_heading("Prefix Rate confirmation suffix")
    assert not page_has_rate_confirmation_heading("Rateconfirmation")
    assert not page_has_rate_confirmation_heading("Rate-confirmation")
    assert not page_has_rate_confirmation_heading("RATE CONFIRMATION")
    assert not page_has_rate_confirmation_heading("rate confirmation")
    assert not page_has_rate_confirmation_heading("Straight Bill of Lading")
    assert not page_has_rate_confirmation_heading("subject to individually determined rates")


def test_filter_excludes_only_matching_pages():
    pdf_bytes = _pdf_with_page_texts(["a", "b", "c", "d", "e"])
    mock_text = MagicMock()
    mock_text.find_rate_confirmation_pages.return_value = [1, 2, 3]

    ratecon_page_filter_service = RateconPageFilterService(
        document_text_service=mock_text
    )
    result = ratecon_page_filter_service.filter_pdf_bytes(pdf_bytes, doc_label="test")

    assert result.success
    assert result.excluded_page_numbers == [1, 2, 3]
    assert result.kept_page_count == 2
    assert result.original_page_count == 5
    assert result.kept_pdf_bytes is not None
    mock_text.find_rate_confirmation_pages.assert_called_once()
    assert mock_text.find_rate_confirmation_pages.call_args.kwargs["prefer_native"] is False


def test_filter_all_pages_rate_confirmation_fail_closed():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    mock_text = MagicMock()
    mock_text.find_rate_confirmation_pages.return_value = [1, 2]

    ratecon_page_filter_service = RateconPageFilterService(
        document_text_service=mock_text
    )
    result = ratecon_page_filter_service.filter_pdf_bytes(pdf_bytes)

    assert not result.success
    assert result.skip_reason == "all_pages_rate_confirmation"
    assert result.kept_pdf_bytes is None
    assert result.excluded_page_numbers == [1, 2]


def test_filter_noop_when_no_hits():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    mock_text = MagicMock()
    mock_text.find_rate_confirmation_pages.return_value = []

    ratecon_page_filter_service = RateconPageFilterService(
        document_text_service=mock_text
    )
    result = ratecon_page_filter_service.filter_pdf_bytes(pdf_bytes)

    assert result.success
    assert result.excluded_page_numbers == []
    assert result.kept_pdf_bytes == pdf_bytes


def test_strip_ratecon_pages_from_pdfs_rejects_all_ratecon_attachment():
    from app.services.attachment_normalizer import AttachmentNormalizerService

    pdf_bytes = _pdf_with_page_texts(["a"])
    with patch(
        "app.services.pod_lifecycle.ratecon_page_filter_service.RateconPageFilterService"
    ) as cls:
        instance = cls.return_value
        instance.filter_pdf_bytes.return_value = MagicMock(
            skip_reason="all_pages_rate_confirmation",
            kept_pdf_bytes=None,
            excluded_page_numbers=[1],
            kept_page_count=0,
        )
        kept, rejected = AttachmentNormalizerService()._strip_ratecon_pages_from_pdfs(
            [("s3://bucket/ratecon.pdf", pdf_bytes)],
            shipment_number="62670",
        )
    assert kept == []
    assert len(rejected) == 1
    assert rejected[0]["rejection_reason"] == "all_pages_rate_confirmation"
