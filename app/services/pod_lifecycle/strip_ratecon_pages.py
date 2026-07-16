"""
Strip rate confirmation pages from a multi-page PDF during POD assess.

Detects pages by the exact ``Rate confirmation`` heading (case-sensitive),
rebuilds a PDF without those pages, and fail-closes when nothing remains.
Used when attachment packs may mix a Ratecon with other documents.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from app.domain.pod_lifecycle.rate_confirmation_heading import page_has_rate_confirmation_heading
from app.tools.pdf_page_text_extractor import PdfPageTextExtractor
from app.tools.pdf_to_images import PdfTooLargeError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StripRateconPagesResult:
    """Outcome of stripping rate confirmation pages from one PDF."""

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
    Strip pages whose heading identifies a rate confirmation document.

    Uses ``PdfPageTextExtractor`` for text/OCR and domain heading match for
    detection; this service rebuilds the PDF. Call during pre-graph assess so
    Ratecon pages never reach staged sources or downstream vision.
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
        Return 1-based page numbers whose text matches a rate confirmation heading.

        Defaults to header-band OCR (``prefer_native=False``) because mixed POD
        packs are often image-only scans.
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
    ) -> StripRateconPagesResult:
        """
        Return kept PDF bytes with rate confirmation pages removed.

        Empty input or all-pages-excluded yields ``skip_reason``.
        """
        if not pdf_bytes:
            return StripRateconPagesResult(
                kept_pdf_bytes=None,
                skip_reason="empty_pdf",
            )

        try:
            excluded = self.find_rate_confirmation_pages(
                pdf_bytes,
                prefer_native=False,
                doc_label=doc_label,
            )
        except PdfTooLargeError:
            raise

        import pikepdf

        with pikepdf.open(io.BytesIO(pdf_bytes)) as src:
            original_count = len(src.pages)
            excluded_set = set(excluded)

            if not excluded_set:
                return StripRateconPagesResult(
                    kept_pdf_bytes=pdf_bytes,
                    excluded_page_numbers=[],
                    kept_page_count=original_count,
                    original_page_count=original_count,
                )

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
                    excluded,
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
