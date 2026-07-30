"""Unit tests for legacy OCR ratecon page trim helpers."""

from __future__ import annotations

from unittest.mock import patch

import fitz

from app.domain.pod_lifecycle.rate_confirmation_heading import page_has_rate_confirmation_heading
from app.services.pod_lifecycle.ratecon_page_trim import (
    RateconPageTrimService,
    resolve_ratecon_page_count,
)
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


def _fake_ocr(match_pages: set[int]):
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

    return fake_ocr


def _ocr_page_numbers(ocr_mock) -> list[int]:
    pages: list[int] = []
    for call in ocr_mock.call_args_list:
        pages.extend(call.kwargs["page_numbers"])
    return pages


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
    ratecon_page_trim_service = RateconPageTrimService()
    with patch.object(
        ratecon_page_trim_service,
        "find_rate_confirmation_pages",
        return_value=[1, 2, 3],
    ) as find_pages:
        result = ratecon_page_trim_service.strip_pdf_bytes(
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
    ratecon_page_trim_service = RateconPageTrimService()
    with patch.object(
        ratecon_page_trim_service,
        "find_rate_confirmation_pages",
        return_value=[1, 2],
    ):
        result = ratecon_page_trim_service.strip_pdf_bytes(pdf_bytes)

    assert not result.success
    assert result.skip_reason == "all_pages_rate_confirmation"
    assert result.kept_pdf_bytes is None
    assert result.excluded_page_numbers == [1, 2]


def test_strip_noop_when_no_hits():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    ratecon_page_trim_service = RateconPageTrimService()
    with patch.object(
        ratecon_page_trim_service,
        "find_rate_confirmation_pages",
        return_value=[],
    ):
        result = ratecon_page_trim_service.strip_pdf_bytes(pdf_bytes)

    assert result.success
    assert result.excluded_page_numbers == []
    assert result.kept_pdf_bytes == pdf_bytes


def test_strip_pdf_bytes_all_pages_rate_confirmation():
    pdf_bytes = _pdf_with_page_texts(["a"])
    ratecon_page_trim_service = RateconPageTrimService()
    with patch.object(
        ratecon_page_trim_service,
        "find_rate_confirmation_pages",
        return_value=[1],
    ):
        result = ratecon_page_trim_service.strip_pdf_bytes(pdf_bytes, doc_label="doc")
    assert result.kept_pdf_bytes is None
    assert result.skip_reason == "all_pages_rate_confirmation"
    assert result.excluded_page_numbers == [1]
    assert result.kept_page_count == 0


def test_strip_p_less_than_r_uses_match_only():
    pdf_bytes = _pdf_with_page_texts(["a", "b"])
    ratecon_page_trim_service = RateconPageTrimService()
    with patch.object(
        ratecon_page_trim_service,
        "find_rate_confirmation_pages",
        return_value=[1],
    ) as find_pages:
        with patch.object(
            ratecon_page_trim_service,
            "_find_pages_terminal_window",
        ) as terminal:
            result = ratecon_page_trim_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=3,
            )

    assert result.excluded_page_numbers == [1]
    find_pages.assert_called_once()
    terminal.assert_not_called()


def test_terminal_front_hit_strips_1_to_r():
    """Page 1 + far page R match → strip 1..R; never OCR mid pages."""
    pdf_bytes = _pdf_with_page_texts(["a"] * 8)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages = {1, 3}

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ) as ocr:
        result = ratecon_page_trim_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=3,
            doc_label="front",
        )

    assert result.success
    assert result.excluded_page_numbers == [1, 2, 3]
    assert result.kept_page_count == 5
    ocr_pages = _ocr_page_numbers(ocr)
    assert set(ocr_pages) == {1, 3, 8}
    assert 4 not in ocr_pages
    assert 5 not in ocr_pages


def test_terminal_front_far_miss_still_strips_window():
    """Page 1 matches, page R misses → log + still strip 1..R."""
    pdf_bytes = _pdf_with_page_texts(["a"] * 8)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages = {1}  # far page 3 does not match

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ):
        with patch(
            "app.services.pod_lifecycle.ratecon_page_trim.logger"
        ) as log:
            result = ratecon_page_trim_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=3,
            )

    assert result.excluded_page_numbers == [1, 2, 3]
    assert any(
        "terminal_far_miss" in str(c.args[0])
        for c in log.warning.call_args_list
    )


def test_terminal_back_hit_strips_p_minus_r_plus_1_to_p():
    """Page P matches → strip back window; OCR terminals + far start only."""
    pdf_bytes = _pdf_with_page_texts(["a"] * 10)
    ratecon_page_trim_service = RateconPageTrimService()
    # Front miss, back hit; far start page 6 also matches
    match_pages = {6, 10}

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ) as ocr:
        result = ratecon_page_trim_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=5,
        )

    assert result.excluded_page_numbers == [6, 7, 8, 9, 10]
    assert result.kept_page_count == 5
    ocr_pages = _ocr_page_numbers(ocr)
    assert set(ocr_pages) == {1, 6, 10}


def test_terminal_back_far_miss_still_strips_window():
    pdf_bytes = _pdf_with_page_texts(["a"] * 10)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages = {10}  # far start page 6 misses

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ):
        with patch(
            "app.services.pod_lifecycle.ratecon_page_trim.logger"
        ) as log:
            result = ratecon_page_trim_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=5,
            )

    assert result.excluded_page_numbers == [6, 7, 8, 9, 10]
    assert any(
        "terminal_far_miss" in str(c.args[0])
        for c in log.warning.call_args_list
    )


def test_terminal_both_hits_prefers_front():
    pdf_bytes = _pdf_with_page_texts(["a"] * 8)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages = {1, 3, 8}

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ):
        result = ratecon_page_trim_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=3,
        )

    assert result.excluded_page_numbers == [1, 2, 3]


def test_terminal_neither_falls_back_to_match_only():
    pdf_bytes = _pdf_with_page_texts(["a"] * 6)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages: set[int] = set()  # terminals miss

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ):
        with patch.object(
            ratecon_page_trim_service,
            "find_rate_confirmation_pages",
            return_value=[3, 4],
        ) as find_pages:
            result = ratecon_page_trim_service.strip_pdf_bytes(
                pdf_bytes,
                ratecon_page_count=2,
            )

    find_pages.assert_called_once()
    assert result.excluded_page_numbers == [3, 4]
    assert result.kept_page_count == 4


def test_resolve_ratecon_page_count_none_when_missing_shipments_row_id():
    assert resolve_ratecon_page_count(None) is None
    assert resolve_ratecon_page_count("") is None


def test_resolve_ratecon_page_count_none_on_cache_miss():
    with patch(
        "app.services.pod_lifecycle.ratecon_page_trim._read_cached_ratecon_extraction_row",
        return_value={"found": False},
    ):
        assert resolve_ratecon_page_count("11111111-1111-4111-8111-111111111111") is None


def test_resolve_ratecon_page_count_reads_cached_metadata():
    with patch(
        "app.services.pod_lifecycle.ratecon_page_trim._read_cached_ratecon_extraction_row",
        return_value={"found": True, "row": {"metadata": {"page_count": 4}}},
    ):
        assert resolve_ratecon_page_count("11111111-1111-4111-8111-111111111111") == 4


def test_terminal_p_equals_r_all_excluded():
    pdf_bytes = _pdf_with_page_texts(["a"] * 3)
    ratecon_page_trim_service = RateconPageTrimService()
    match_pages = {1, 3}

    with patch.object(
        ratecon_page_trim_service._page_text_extractor,
        "ocr_pages",
        side_effect=_fake_ocr(match_pages),
    ):
        result = ratecon_page_trim_service.strip_pdf_bytes(
            pdf_bytes,
            ratecon_page_count=3,
        )

    assert not result.success
    assert result.skip_reason == "all_pages_rate_confirmation"
    assert result.excluded_page_numbers == [1, 2, 3]
