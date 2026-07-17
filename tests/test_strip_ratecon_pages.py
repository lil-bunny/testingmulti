"""Unit tests for rate-confirmation heading match and strip_ratecon_pages."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import fitz

from app.domain.pod_lifecycle.rate_confirmation_heading import page_has_rate_confirmation_heading
from app.services.pod_lifecycle.strip_ratecon_pages import StripRateconPagesService
from app.tools.pdf_page_text_extractor import PageText


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


def test_strip_p_less_than_r_uses_match_only():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    strip_ratecon_pages_service = StripRateconPagesService()
    with patch.object(
        strip_ratecon_pages_service,
        "find_rate_confirmation_pages",
        return_value=[1],
    ) as find_pages:
        with patch.object(
            strip_ratecon_pages_service,
            "_find_pages_both_ends_smart",
        ) as smart:
            result = strip_ratecon_pages_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=3,
            )

    assert result.excluded_page_numbers == [1]
    find_pages.assert_called_once()
    smart.assert_not_called()


def test_smart_contiguous_strip_on_front_hit_and_window_end():
    """Hit page 1, confirm page 3 (R=3) → strip 1..3 without walking the rest."""
    pdf_bytes = _pdf_with_page_texts(["a"] * 8)
    strip_ratecon_pages_service = StripRateconPagesService()
    # Pages that match heading when OCR'd
    match_pages = {1, 3}

    def fake_ocr(pdf_bytes_arg, *, page_numbers, header_only, doc_label):
        del pdf_bytes_arg, header_only, doc_label
        return [
            PageText(
                page_number=n,
                text="Rate confirmation" if n in match_pages else "BOL",
                source="ocr",
            )
            for n in page_numbers
        ]

    with patch.object(
        strip_ratecon_pages_service._page_text_extractor,
        "ocr_pages",
        side_effect=fake_ocr,
    ) as ocr:
        result = strip_ratecon_pages_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=3,
            doc_label="smart",
        )

    assert result.success
    assert result.excluded_page_numbers == [1, 2, 3]
    assert result.kept_page_count == 5
    # First round OCR 1+8; then window confirm OCR 3 (1 cached). Never all 8.
    ocr_pages = []
    for call in ocr.call_args_list:
        ocr_pages.extend(call.kwargs["page_numbers"])
    assert 1 in ocr_pages
    assert 3 in ocr_pages
    assert 4 not in ocr_pages
    assert 5 not in ocr_pages


def test_smart_stop_when_hit_count_equals_r():
    pdf_bytes = _pdf_with_page_texts(["a"] * 6)
    strip_ratecon_pages_service = StripRateconPagesService()
    match_pages = {1, 2}

    def fake_ocr(pdf_bytes_arg, *, page_numbers, header_only, doc_label):
        del pdf_bytes_arg, header_only, doc_label
        return [
            PageText(
                page_number=n,
                text="Rate confirmation" if n in match_pages else "POD",
                source="ocr",
            )
            for n in page_numbers
        ]

    with patch.object(
        strip_ratecon_pages_service._page_text_extractor,
        "ocr_pages",
        side_effect=fake_ocr,
    ):
        # Force contiguous window miss so hit-count path stops (R=2, pages 1+2 contiguous).
        with patch.object(
            strip_ratecon_pages_service,
            "_try_contiguous_window",
            return_value=None,
        ):
            result = strip_ratecon_pages_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=2,
            )

    assert result.excluded_page_numbers == [1, 2]


def test_smart_window_end_miss_continues_then_strips_hits_at_meet():
    pdf_bytes = _pdf_with_page_texts(["a"] * 4)
    strip_ratecon_pages_service = StripRateconPagesService()
    # Only page 2 matches; window 2..3 fails because 3 misses → walk to meet → strip {2}
    match_pages = {2}

    def fake_ocr(pdf_bytes_arg, *, page_numbers, header_only, doc_label):
        del pdf_bytes_arg, header_only, doc_label
        return [
            PageText(
                page_number=n,
                text="Rate confirmation" if n in match_pages else "POD",
                source="ocr",
            )
            for n in page_numbers
        ]

    with patch.object(
        strip_ratecon_pages_service._page_text_extractor,
        "ocr_pages",
        side_effect=fake_ocr,
    ):
        result = strip_ratecon_pages_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=2,
        )

    assert result.excluded_page_numbers == [2]
    assert result.kept_page_count == 3


def test_smart_hit_count_ignores_non_contiguous_hits():
    """Page 1 + last page both match with R=2 must not strip those ends as a block."""
    pdf_bytes = _pdf_with_page_texts(["a"] * 6)
    strip_ratecon_pages_service = StripRateconPagesService()
    match_pages = {1, 6}

    def fake_ocr(pdf_bytes_arg, *, page_numbers, header_only, doc_label):
        del pdf_bytes_arg, header_only, doc_label
        return [
            PageText(
                page_number=n,
                text="Rate confirmation" if n in match_pages else "POD",
                source="ocr",
            )
            for n in page_numbers
        ]

    with patch.object(
        strip_ratecon_pages_service._page_text_extractor,
        "ocr_pages",
        side_effect=fake_ocr,
    ):
        with patch.object(
            strip_ratecon_pages_service,
            "_try_contiguous_window",
            return_value=None,
        ):
            result = strip_ratecon_pages_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=2,
            )

    # Walk completes; strip accumulated hits only (not treated as contiguous R-block).
    assert result.excluded_page_numbers == [1, 6]
