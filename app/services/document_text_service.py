"""
Reusable PDF → text acquisition for LLM and classification callers.

Prefers embedded (native) text; rasterizes and OCRs only when text is sparse or
absent. Page-at-a-time rendering keeps peak memory bounded.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from app.core.config import settings
from app.tools.pdf_raster import (
    PdfTooLargeError,
    make_temp_pdf,
    render_pdf_page_image,
)
from app.tools.pdf_text import (
    PageText,
    crop_header_band,
    extract_native_page_texts,
    is_sparse_native_text,
    ocr_image_rgb,
    page_has_rate_confirmation_heading,
    pdf_page_count,
)

logger = logging.getLogger(__name__)


class DocumentTextService:
    """
    Shared entrypoint for turning PDF bytes into page text.

    Use this instead of calling native extract / OCR helpers ad hoc from nodes or
    workflows so budgeting, header crops, and sparse-text policy stay consistent.
    """

    def extract_pages(
        self,
        pdf_bytes: bytes,
        *,
        prefer_native: bool = True,
        ocr_if_sparse: bool = True,
        header_only_ocr: bool = False,
        doc_label: str = "doc",
    ) -> list[PageText]:
        """
        Return per-page text for ``pdf_bytes``.

        When ``prefer_native`` and a page has enough embedded text, skip OCR for
        that page. When ``ocr_if_sparse``, only sparse/empty pages are rasterized
        and OCR'd (one page at a time). ``header_only_ocr`` crops the top band
        before OCR when only a heading is needed.
        """
        native_pages = extract_native_page_texts(pdf_bytes) if prefer_native else []
        page_count = len(native_pages) if native_pages else pdf_page_count(pdf_bytes)
        if page_count < 1:
            return []

        if prefer_native and native_pages:
            need_ocr = [
                p
                for p in native_pages
                if ocr_if_sparse
                and is_sparse_native_text(
                    p.text, min_chars=settings.OCR_NATIVE_TEXT_MIN_CHARS
                )
            ]
            if not need_ocr:
                return native_pages
            ocr_by_page = {
                p.page_number: p
                for p in self._ocr_selected_pages(
                    pdf_bytes,
                    page_numbers=[p.page_number for p in need_ocr],
                    header_only=header_only_ocr,
                    doc_label=doc_label,
                )
            }
            merged: list[PageText] = []
            for p in native_pages:
                if p.page_number in ocr_by_page and ocr_by_page[p.page_number].text:
                    merged.append(ocr_by_page[p.page_number])
                else:
                    merged.append(p)
            return merged

        return self._ocr_selected_pages(
            pdf_bytes,
            page_numbers=list(range(1, page_count + 1)),
            header_only=header_only_ocr,
            doc_label=doc_label,
        )

    def extract_full_text(
        self,
        pdf_bytes: bytes,
        *,
        prefer_native: bool = True,
        ocr_if_sparse: bool = True,
        doc_label: str = "doc",
    ) -> str:
        """Concatenate non-empty page texts into one string for a text LLM."""
        pages = self.extract_pages(
            pdf_bytes,
            prefer_native=prefer_native,
            ocr_if_sparse=ocr_if_sparse,
            header_only_ocr=False,
            doc_label=doc_label,
        )
        return "\n\n".join(
            f"--- Page {p.page_number} ---\n{p.text}" for p in pages if p.text
        )

    def find_rate_confirmation_pages(
        self,
        pdf_bytes: bytes,
        *,
        prefer_native: bool = True,
        doc_label: str = "doc",
    ) -> list[int]:
        """
        Return 1-based page numbers whose text matches a rate confirmation heading.

        Uses header-band OCR when pages lack reliable native text so scanned packs
        still detect the heading without OCRing the full page body.
        """
        pages = self.extract_pages(
            pdf_bytes,
            prefer_native=prefer_native,
            ocr_if_sparse=True,
            header_only_ocr=True,
            doc_label=doc_label,
        )
        hits: list[int] = []
        for page in pages:
            if page_has_rate_confirmation_heading(page.text):
                hits.append(page.page_number)
        return hits

    def _ocr_selected_pages(
        self,
        pdf_bytes: bytes,
        *,
        page_numbers: list[int],
        header_only: bool,
        doc_label: str,
    ) -> list[PageText]:
        """Rasterize and OCR only the given 1-based page numbers."""
        tmp_path: str | None = None
        results: list[PageText] = []
        try:
            fd, tmp_path = make_temp_pdf(prefix=f"{doc_label}_ocr_")
            try:
                os.write(fd, pdf_bytes)
            finally:
                os.close(fd)

            for page_number in page_numbers:
                image = None
                header = None
                try:
                    image = render_pdf_page_image(
                        tmp_path,
                        page_number,
                        dpi=settings.OCR_DPI,
                        max_page_bytes=settings.POD_CONVERT_MAX_PAGE_BYTES,
                        max_side_px=settings.OCR_IMAGE_MAX_SIDE_PX,
                    )
                    target = (
                        crop_header_band(
                            image, fraction=settings.OCR_HEADER_FRACTION
                        )
                        if header_only
                        else image
                    )
                    if header_only:
                        header = target
                    text = ocr_image_rgb(target)
                    results.append(
                        PageText(
                            page_number=page_number,
                            text=text,
                            source="ocr" if text else "empty",
                        )
                    )
                except PdfTooLargeError:
                    raise
                except Exception:
                    logger.exception(
                        "document_text: OCR failed doc=%s page=%s",
                        doc_label,
                        page_number,
                    )
                    results.append(
                        PageText(page_number=page_number, text="", source="empty")
                    )
                finally:
                    if header is not None and header is not image:
                        try:
                            header.close()
                        except Exception:
                            pass
                    if image is not None:
                        try:
                            image.close()
                        except Exception:
                            pass
            return results
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
