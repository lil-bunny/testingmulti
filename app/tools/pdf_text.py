"""
Stateless PDF text helpers shared by document extraction flows.

Provides native (embedded) text, OCR over page images, header cropping, and
heading-match utilities. No S3/DB — callers own temp files and memory budgets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

# Exact heading phrase (case-sensitive, including the space).
RATE_CONFIRMATION_NEEDLE = "Rate confirmation"
_NATIVE_SPARSE_CHARS = 40


@dataclass(frozen=True)
class PageText:
    """One PDF page's text and how it was obtained."""

    page_number: int  # 1-based
    text: str
    source: str  # "native" | "ocr" | "empty"


def page_has_rate_confirmation_heading(text: str) -> bool:
    """True when page text contains the exact ``Rate confirmation`` heading."""
    return RATE_CONFIRMATION_NEEDLE in (text or "")



def is_sparse_native_text(text: str, *, min_chars: int = _NATIVE_SPARSE_CHARS) -> bool:
    """True when embedded text is too short to trust without OCR."""
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
                logger.exception("pdf_text: native extract failed page=%s", i + 1)
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
    """Return page count for ``pdf_bytes`` via PyMuPDF."""
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
    """
    OCR a PIL RGB image to newline-joined text.

    Callers should release the image promptly to limit peak memory.
    """
    import numpy as np

    engine = _get_ocr_engine()
    arr = np.asarray(image.convert("RGB"))
    result, _ = engine(arr)
    if not result:
        return ""
    lines = [str(row[1]) for row in result if row and len(row) > 1 and row[1]]
    return "\n".join(lines).strip()


def crop_header_band(image: Any, *, fraction: float = 0.35) -> Any:
    """Return the top ``fraction`` of a page image (for cheap heading OCR)."""
    frac = min(0.95, max(0.1, float(fraction)))
    w, h = image.size
    header_h = max(1, int(h * frac))
    return image.crop((0, 0, w, header_h))
