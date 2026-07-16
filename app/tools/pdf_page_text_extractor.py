"""
PDF → per-page text for LLM and classification callers.

Prefer native text; OCR sparse/empty pages one at a time. No S3/DB.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.tools.pdf_to_images import (
    PdfTooLargeError,
    make_temp_pdf,
    render_pdf_page_image,
)

logger = logging.getLogger(__name__)

_NATIVE_SPARSE_CHARS = 40


@dataclass(frozen=True)
class PageText:
    """One PDF page's text and how it was obtained."""

    page_number: int  # 1-based
    text: str
    source: str  # "native" | "ocr" | "empty"


def is_sparse_native_text(text: str, *, min_chars: int = _NATIVE_SPARSE_CHARS) -> bool:
    """True when embedded text is shorter than ``min_chars`` (OCR may be needed)."""
    return len((text or "").strip()) < max(0, int(min_chars))


def extract_native_page_texts(pdf_bytes: bytes) -> list[PageText]:
    """Extract embedded PDF text per page via PyMuPDF (no rasterization or OCR)."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        out: list[PageText] = []
        for i in range(doc.page_count):
            try:
                raw = doc.load_page(i).get_text() or ""
            except Exception:
                logger.exception(
                    "pdf_page_text_extractor: native extract failed page=%s", i + 1
                )
                raw = ""
            text = raw.strip()
            out.append(
                PageText(
                    page_number=i + 1,
                    text=text,
                    source="native" if text else "empty",
                )
            )
        return out
    finally:
        doc.close()


def pdf_page_count(pdf_bytes: bytes) -> int:
    """Return PDF page count via PyMuPDF."""
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        return int(doc.page_count)
    finally:
        doc.close()


_OCR_ENGINE: Any = None


def _get_ocr_engine() -> Any:
    """Lazy-load RapidOCR once; model init is expensive."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        _OCR_ENGINE = RapidOCR()
    return _OCR_ENGINE


def ocr_image_rgb(image: Any) -> str:
    """OCR a PIL RGB image to newline-joined text; caller should close the image."""
    import numpy as np

    engine = _get_ocr_engine()
    arr = np.asarray(image.convert("RGB"))
    result, _ = engine(arr)
    if not result:
        return ""
    lines = [str(row[1]) for row in result if row and len(row) > 1 and row[1]]
    return "\n".join(lines).strip()


def crop_header_band(image: Any, *, fraction: float = 0.35) -> Any:
    """Return the top ``fraction`` of a page image (cheap heading OCR)."""
    frac = min(0.95, max(0.1, float(fraction)))
    w, h = image.size
    header_h = max(1, int(h * frac))
    return image.crop((0, 0, w, header_h))


class PdfPageTextExtractor:
    """
    Turn PDF bytes into per-page text with a consistent native-first OCR policy.

    Sparse pages are rasterized one at a time; optional header crop for title checks.
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

        Flow: native extract when preferred → OCR only sparse/empty pages (or all
        pages when prefer_native is false). ``header_only_ocr`` crops before OCR.
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

    def _ocr_selected_pages(
        self,
        pdf_bytes: bytes,
        *,
        page_numbers: list[int],
        header_only: bool,
        doc_label: str,
    ) -> list[PageText]:
        """Rasterize and OCR the given 1-based page numbers (temp file + cleanup)."""
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
                        "pdf_page_text_extractor: OCR failed doc=%s page=%s",
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
