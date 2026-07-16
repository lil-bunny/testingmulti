"""Unit tests for rate-confirmation heading match and strip_ratecon_pages."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import fitz

from app.domain.pod_lifecycle.rate_confirmation_heading import page_has_rate_confirmation_heading
from app.services.pod_lifecycle.strip_ratecon_pages import StripRateconPagesService


def _pdf_with_page_texts(texts: list[str]) -> bytes:
    """Build a minimal multi-page PDF. Heading detection is mocked in strip tests."""
    doc = fitz.open()
    try:
        for _ in texts:
            doc.new_page(width=612, height=792)
        return doc.tobytes()
    finally:
        doc.close()


def test_page_has_rate_confirmation_heading_case_sensitive_ignores_spaces():
    assert page_has_rate_confirmation_heading("Rate confirmation\nShipment ID")
    assert page_has_rate_confirmation_heading("Prefix Rate confirmation suffix")
    assert page_has_rate_confirmation_heading("Rateconfirmation")
    assert page_has_rate_confirmation_heading("Rate  confirmation")  # OCR multi-space
    assert not page_has_rate_confirmation_heading("Rate-confirmation")
    assert not page_has_rate_confirmation_heading("RATE CONFIRMATION")
    assert not page_has_rate_confirmation_heading("rate confirmation")
    assert not page_has_rate_confirmation_heading("Straight Bill of Lading")
    assert not page_has_rate_confirmation_heading(
        "subject to individually determined rates"
    )


def test_strip_excludes_only_matching_pages():
    pdf_bytes = _pdf_with_page_texts(["a", "b", "c", "d", "e"])
    strip_ratecon_pages_service = StripRateconPagesService()
    with patch.object(
        strip_ratecon_pages_service,
        "find_rate_confirmation_pages",
        return_value=[1, 2, 3],
    ) as find_pages:
        result = strip_ratecon_pages_service.strip_pdf_bytes(
            pdf_bytes, doc_label="test"
        )

    assert result.success
    assert result.excluded_page_numbers == [1, 2, 3]
    assert result.kept_page_count == 2
    assert result.original_page_count == 5
    assert result.kept_pdf_bytes is not None
    find_pages.assert_called_once()
    assert find_pages.call_args.kwargs["prefer_native"] is False


def test_strip_all_pages_rate_confirmation_fail_closed():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    strip_ratecon_pages_service = StripRateconPagesService()
    with patch.object(
        strip_ratecon_pages_service,
        "find_rate_confirmation_pages",
        return_value=[1, 2],
    ):
        result = strip_ratecon_pages_service.strip_pdf_bytes(pdf_bytes)

    assert not result.success
    assert result.skip_reason == "all_pages_rate_confirmation"
    assert result.kept_pdf_bytes is None
    assert result.excluded_page_numbers == [1, 2]


def test_strip_noop_when_no_hits():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    strip_ratecon_pages_service = StripRateconPagesService()
    with patch.object(
        strip_ratecon_pages_service,
        "find_rate_confirmation_pages",
        return_value=[],
    ):
        result = strip_ratecon_pages_service.strip_pdf_bytes(pdf_bytes)

    assert result.success
    assert result.excluded_page_numbers == []
    assert result.kept_pdf_bytes == pdf_bytes


def test_strip_ratecon_pages_from_pdfs_rejects_all_ratecon_attachment():
    from app.services.attachment_normalizer import AttachmentNormalizerService

    pdf_bytes = _pdf_with_page_texts(["a"])
    with patch(
        "app.services.pod_lifecycle.strip_ratecon_pages.StripRateconPagesService"
    ) as cls:
        instance = cls.return_value
        instance.strip_pdf_bytes.return_value = MagicMock(
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
