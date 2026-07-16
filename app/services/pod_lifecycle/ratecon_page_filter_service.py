"""
Remove rate confirmation pages from a multi-page PDF before downstream use.

Detects pages by the exact ``Rate confirmation`` heading (case-sensitive),
rebuilds a PDF without those pages, and fail-closes when nothing remains.
Used when attachment packs may mix a Ratecon with other documents.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field

from app.services.document_text_service import DocumentTextService
from app.tools.pdf_raster import PdfTooLargeError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RateconPageFilterResult:
    """Outcome of stripping rate confirmation pages from one PDF."""

    kept_pdf_bytes: bytes | None
    excluded_page_numbers: list[int] = field(default_factory=list)
    kept_page_count: int = 0
    original_page_count: int = 0
    skip_reason: str | None = None

    @property
    def success(self) -> bool:
        return self.kept_pdf_bytes is not None and self.kept_page_count > 0


class RateconPageFilterService:
    """
    Strip pages whose heading identifies a rate confirmation document.

    Relies on ``DocumentTextService`` for text/OCR; this service only decides
    which pages to drop and rebuilds the PDF. Call during pre-graph assess so
    Ratecon pages never reach staged sources or downstream vision.
    """

    def __init__(
        self,
        document_text_service: DocumentTextService | None = None,
    ) -> None:
        self._document_text_service = document_text_service or DocumentTextService()

    def filter_pdf_bytes(
        self,
        pdf_bytes: bytes,
        *,
        doc_label: str = "doc",
    ) -> RateconPageFilterResult:
        """
        Return kept PDF bytes with rate confirmation pages removed.

        Prefers header OCR (``prefer_native=False``) because mixed packs are often
        image-only scans. Empty input or all-pages-excluded yields ``skip_reason``.
        """
        if not pdf_bytes:
            return RateconPageFilterResult(
                kept_pdf_bytes=None,
                skip_reason="empty_pdf",
            )

        try:
            excluded = self._document_text_service.find_rate_confirmation_pages(
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
                return RateconPageFilterResult(
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
                    "ratecon_page_filter: all pages excluded doc=%s pages=%s excluded=%s",
                    doc_label,
                    original_count,
                    excluded,
                )
                return RateconPageFilterResult(
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
            "ratecon_page_filter: stripped ratecon pages doc=%s original=%s "
            "excluded=%s kept=%s",
            doc_label,
            original_count,
            sorted(excluded_set),
            kept_count,
        )
        return RateconPageFilterResult(
            kept_pdf_bytes=kept_bytes,
            excluded_page_numbers=sorted(excluded_set),
            kept_page_count=kept_count,
            original_page_count=original_count,
        )
