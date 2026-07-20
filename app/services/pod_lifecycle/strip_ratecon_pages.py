"""
Strip rate confirmation pages from mixed POD PDFs during pre-graph assess.

When ``ratecon_page_count`` (R) is known from ratecon
``document_analysis.metadata.page_count`` and ``P >= R``, OCR page 1 and page P;
on a terminal hit strip the contiguous R-window (verify far end, log miss, still
strip). Otherwise OCR all pages and strip heading matches only.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from app.domain.pod_lifecycle.rate_confirmation_heading import (
    page_has_rate_confirmation_heading,
)
from app.tools.pdf_page_text_extractor import (
    PdfPageTextExtractor,
    pdf_page_count,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StripRateconPagesResult:
    """Kept PDF bytes after rate confirmation pages are removed (or a skip reason)."""

    kept_pdf_bytes: bytes | None
    excluded_page_numbers: list[int] = field(default_factory=list)
    kept_page_count: int = 0
    original_page_count: int = 0
    skip_reason: str | None = None

    @property
    def success(self) -> bool:
        return self.kept_pdf_bytes is not None and self.kept_page_count > 0


class StripRateconPagesService:
    """
    Remove rate confirmation pages from one PDF before POD staging.

    Smart path (R known and P >= R): OCR terminals (1 and P); front hit strips
    ``1..R``, back hit strips ``P-R+1..P`` (front wins if both). Far-end verify
    miss is logged but still strips by count. Neither terminal → match-only.
    Fallback (missing R or P < R): OCR all pages, strip heading matches only.
    """

    def __init__(
        self,
        page_text_extractor: PdfPageTextExtractor | None = None,
    ) -> None:
        self._page_text_extractor = page_text_extractor or PdfPageTextExtractor()

    def find_rate_confirmation_pages(
        self,
        pdf_bytes: bytes,
        *,
        prefer_native: bool = False,
        doc_label: str = "doc",
    ) -> list[int]:
        """
        Return 1-based page numbers whose text matches the rate confirmation heading.

        Defaults to header-band OCR because mixed POD packs are often image-only.
        """
        pages = self._page_text_extractor.extract_pages(
            pdf_bytes,
            prefer_native=prefer_native,
            ocr_if_sparse=True,
            header_only_ocr=True,
            doc_label=doc_label,
        )
        return [
            page.page_number
            for page in pages
            if page_has_rate_confirmation_heading(page.text)
        ]

    def strip_pdf_bytes(
        self,
        pdf_bytes: bytes,
        *,
        doc_label: str = "doc",
        ratecon_page_count: int | None = None,
    ) -> StripRateconPagesResult:
        """
        Rebuild ``pdf_bytes`` without rate confirmation pages.

        Outcomes: unchanged bytes (no hits), filtered bytes, or skip_reason
        (``empty_pdf`` / ``all_pages_rate_confirmation``).
        """
        if not pdf_bytes:
            return StripRateconPagesResult(
                kept_pdf_bytes=None,
                skip_reason="empty_pdf",
            )

        page_count = pdf_page_count(pdf_bytes)
        if page_count < 1:
            return StripRateconPagesResult(
                kept_pdf_bytes=None,
                skip_reason="empty_pdf",
            )

        r = self._normalize_ratecon_page_count(ratecon_page_count)
        if r is None or page_count < r:
            excluded = self.find_rate_confirmation_pages(
                pdf_bytes,
                prefer_native=False,
                doc_label=doc_label,
            )
            logger.info(
                "strip_ratecon_pages: match_only doc=%s P=%s R=%s hits=%s",
                doc_label,
                page_count,
                r,
                excluded,
            )
        else:
            excluded = self._find_pages_terminal_window(
                pdf_bytes,
                page_count=page_count,
                ratecon_page_count=r,
                doc_label=doc_label,
            )
            logger.info(
                "strip_ratecon_pages: terminal doc=%s P=%s R=%s excluded=%s",
                doc_label,
                page_count,
                r,
                excluded,
            )

        return self._rebuild_without_pages(
            pdf_bytes,
            excluded=excluded,
            original_count=page_count,
            doc_label=doc_label,
        )

    @staticmethod
    def _normalize_ratecon_page_count(value: int | None) -> int | None:
        if value is None:
            return None
        try:
            n = int(value)
        except (TypeError, ValueError):
            return None
        return n if n >= 1 else None

    def _ocr_page_matches(
        self,
        pdf_bytes: bytes,
        page_numbers: list[int],
        *,
        doc_label: str,
        match_cache: dict[int, bool],
    ) -> dict[int, bool]:
        """OCR missing pages; update and return match_cache for requested pages."""
        need = [n for n in page_numbers if n not in match_cache]
        if need:
            pages = self._page_text_extractor.ocr_pages(
                pdf_bytes,
                page_numbers=need,
                header_only=True,
                doc_label=doc_label,
            )
            for page in pages:
                match_cache[page.page_number] = page_has_rate_confirmation_heading(
                    page.text
                )
        return {n: bool(match_cache.get(n)) for n in page_numbers}

    def _find_pages_terminal_window(
        self,
        pdf_bytes: bytes,
        *,
        page_count: int,
        ratecon_page_count: int,
        doc_label: str,
    ) -> list[int]:
        """
        OCR page 1 and page P; strip an R-page window from a matching terminal.

        Front hit → ``1..R`` (wins if both terminals match). Back hit →
        ``P-R+1..P``. Far-end heading miss is logged; window still stripped.
        Neither terminal → match-only full scan.
        """
        r = ratecon_page_count
        p = page_count
        match_cache: dict[int, bool] = {}
        terminals = [1] if p == 1 else [1, p]
        matches = self._ocr_page_matches(
            pdf_bytes,
            terminals,
            doc_label=doc_label,
            match_cache=match_cache,
        )
        front_hit = bool(matches.get(1))
        back_hit = bool(matches.get(p)) if p > 1 else front_hit

        if front_hit and back_hit and p > 1:
            logger.info(
                "strip_ratecon_pages: both_terminals_match doc=%s P=%s R=%s "
                "choosing_front",
                doc_label,
                p,
                r,
            )

        if front_hit:
            start, end = 1, r
            far = end
            if far != 1:
                far_matches = self._ocr_page_matches(
                    pdf_bytes,
                    [far],
                    doc_label=doc_label,
                    match_cache=match_cache,
                )
                far_ok = bool(far_matches.get(far))
            else:
                far_ok = True
            if not far_ok:
                logger.warning(
                    "strip_ratecon_pages: terminal_far_miss doc=%s anchor=front "
                    "window=%s..%s far_page=%s still_stripping",
                    doc_label,
                    start,
                    end,
                    far,
                )
            else:
                logger.info(
                    "strip_ratecon_pages: terminal_front doc=%s window=%s..%s "
                    "far_match=%s",
                    doc_label,
                    start,
                    end,
                    far_ok,
                )
            return list(range(start, end + 1))

        if back_hit:
            start, end = p - r + 1, p
            far = start
            if far != p:
                far_matches = self._ocr_page_matches(
                    pdf_bytes,
                    [far],
                    doc_label=doc_label,
                    match_cache=match_cache,
                )
                far_ok = bool(far_matches.get(far))
            else:
                far_ok = True
            if not far_ok:
                logger.warning(
                    "strip_ratecon_pages: terminal_far_miss doc=%s anchor=back "
                    "window=%s..%s far_page=%s still_stripping",
                    doc_label,
                    start,
                    end,
                    far,
                )
            else:
                logger.info(
                    "strip_ratecon_pages: terminal_back doc=%s window=%s..%s "
                    "far_match=%s",
                    doc_label,
                    start,
                    end,
                    far_ok,
                )
            return list(range(start, end + 1))

        logger.info(
            "strip_ratecon_pages: neither_terminal doc=%s P=%s R=%s → match_only",
            doc_label,
            p,
            r,
        )
        return self.find_rate_confirmation_pages(
            pdf_bytes,
            prefer_native=False,
            doc_label=doc_label,
        )

    def _rebuild_without_pages(
        self,
        pdf_bytes: bytes,
        *,
        excluded: list[int],
        original_count: int,
        doc_label: str,
    ) -> StripRateconPagesResult:
        import pikepdf

        excluded_set = set(excluded)
        if not excluded_set:
            return StripRateconPagesResult(
                kept_pdf_bytes=pdf_bytes,
                excluded_page_numbers=[],
                kept_page_count=original_count,
                original_page_count=original_count,
            )

        with pikepdf.open(io.BytesIO(pdf_bytes)) as src:
            # Delete highest indexes first so remaining indexes stay valid.
            for page_num in sorted(excluded_set, reverse=True):
                idx = page_num - 1
                if 0 <= idx < len(src.pages):
                    del src.pages[idx]

            kept_count = len(src.pages)
            if kept_count < 1:
                logger.info(
                    "strip_ratecon_pages: all pages excluded doc=%s pages=%s excluded=%s",
                    doc_label,
                    original_count,
                    sorted(excluded_set),
                )
                return StripRateconPagesResult(
                    kept_pdf_bytes=None,
                    excluded_page_numbers=sorted(excluded_set),
                    kept_page_count=0,
                    original_page_count=original_count,
                    skip_reason="all_pages_rate_confirmation",
                )

            buf = io.BytesIO()
            src.save(buf)
            kept_bytes = buf.getvalue()

        logger.info(
            "strip_ratecon_pages: stripped doc=%s original=%s excluded=%s kept=%s",
            doc_label,
            original_count,
            sorted(excluded_set),
            kept_count,
        )
        return StripRateconPagesResult(
            kept_pdf_bytes=kept_bytes,
            excluded_page_numbers=sorted(excluded_set),
            kept_page_count=kept_count,
            original_page_count=original_count,
        )
