"""
PDF → per-page text for LLM and classification callers.

Prefer native text; OCR sparse/empty pages with bounded thread parallelism. No S3/DB.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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
_OCR_ENGINE: Any = None


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


def _get_ocr_engine() -> Any:
    """Lazy-load RapidOCR once; model init is expensive."""
    global _OCR_ENGINE
    if _OCR_ENGINE is None:
        from rapidocr_onnxruntime import RapidOCR

        # App ThreadPool owns concurrency; keep ORT per-run threads at 1.
        intra = max(1, int(settings.OCR_INTRA_OP_THREADS))
        _OCR_ENGINE = RapidOCR(
            intra_op_num_threads=intra,
            inter_op_num_threads=1,
        )
    return _OCR_ENGINE


def ocr_image_rgb(image: Any) -> str:
    """OCR a PIL RGB image to newline-joined text; caller should close the image."""
    import numpy as np

    engine = _get_ocr_engine()
    owned_rgb = None
    arr = None
    try:
        if getattr(image, "mode", None) == "RGB":
            rgb = image
        else:
            owned_rgb = image.convert("RGB")
            rgb = owned_rgb
        # Copy so the ndarray does not pin the PIL buffer.
        arr = np.array(rgb, dtype=np.uint8, copy=True)
    finally:
        if owned_rgb is not None:
            try:
                owned_rgb.close()
            except Exception:
                pass
    try:
        result, _ = engine(arr)
    finally:
        del arr
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
    PDF bytes → per-page text (native-first, sparse OCR).

    Header-only strip uses clip + strip DPI; pages fan out under ``OCR_MAX_WORKERS``.
    One RapidOCR/ONNX session process-wide.
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

        Flow: native when preferred → OCR sparse/empty pages (or all when
        prefer_native is false). ``header_only_ocr`` clips the top band at raster.
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
                for p in self.ocr_pages(
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

        return self.ocr_pages(
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

    def _ocr_one_page(
        self,
        pdf_path: str,
        page_number: int,
        *,
        header_only: bool,
        doc_label: str,
    ) -> PageText:
        """Rasterize and OCR one 1-based page; safe to call from a worker thread."""
        image = None
        try:
            if header_only:
                image = render_pdf_page_image(
                    pdf_path,
                    page_number,
                    dpi=settings.OCR_STRIP_DPI,
                    max_page_bytes=settings.POD_CONVERT_MAX_PAGE_BYTES,
                    max_side_px=settings.OCR_STRIP_IMAGE_MAX_SIDE_PX,
                    header_fraction=settings.OCR_HEADER_FRACTION,
                )
            else:
                image = render_pdf_page_image(
                    pdf_path,
                    page_number,
                    dpi=settings.OCR_DPI,
                    max_page_bytes=settings.POD_CONVERT_MAX_PAGE_BYTES,
                    max_side_px=settings.OCR_IMAGE_MAX_SIDE_PX,
                )
            text = ocr_image_rgb(image)
            return PageText(
                page_number=page_number,
                text=text,
                source="ocr" if text else "empty",
            )
        except PdfTooLargeError:
            raise
        except Exception:
            logger.exception(
                "pdf_page_text_extractor: OCR failed doc=%s page=%s",
                doc_label,
                page_number,
            )
            return PageText(page_number=page_number, text="", source="empty")
        finally:
            if image is not None:
                try:
                    image.close()
                except Exception:
                    pass

    def ocr_pages(
        self,
        pdf_bytes: bytes,
        *,
        page_numbers: list[int],
        header_only: bool = False,
        doc_label: str = "doc",
    ) -> list[PageText]:
        """
        Rasterize and OCR the given 1-based page numbers.

        Flow: write temp PDF → fan out under ``OCR_MAX_WORKERS`` → return in
        ``page_numbers`` order. ``PdfTooLargeError`` propagates.
        """
        if not page_numbers:
            return []

        tmp_path: str | None = None
        try:
            fd, tmp_path = make_temp_pdf(prefix=f"{doc_label}_ocr_")
            try:
                os.write(fd, pdf_bytes)
            finally:
                os.close(fd)

            workers = max(1, min(int(settings.OCR_MAX_WORKERS), len(page_numbers)))
            _get_ocr_engine()

            if workers == 1 or len(page_numbers) == 1:
                return [
                    self._ocr_one_page(
                        tmp_path,
                        page_number,
                        header_only=header_only,
                        doc_label=doc_label,
                    )
                    for page_number in page_numbers
                ]

            by_page: dict[int, PageText] = {}
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {
                    executor.submit(
                        self._ocr_one_page,
                        tmp_path,
                        page_number,
                        header_only=header_only,
                        doc_label=doc_label,
                    ): page_number
                    for page_number in page_numbers
                }
                for future in as_completed(futures):
                    page_number = futures[future]
                    try:
                        by_page[page_number] = future.result()
                    except PdfTooLargeError:
                        for pending in futures:
                            pending.cancel()
                        raise
            return [by_page[n] for n in page_numbers if n in by_page]
        finally:
            if tmp_path and os.path.isfile(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
