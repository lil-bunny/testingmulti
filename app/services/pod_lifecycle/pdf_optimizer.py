"""Compress large POD PDFs before Turvo TMS upload (10 MB API limit)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import img2pdf
from pdf2image import convert_from_path
from PIL import Image

from app.core.logger import get_logger

logger = get_logger(__name__)


class PodPdfOptimizeError(Exception):
    """Raised when a PDF cannot be reduced below the TMS upload size limit."""


def _resize_page(image: Image.Image, max_side_px: int) -> Image.Image:
    if not max_side_px or max_side_px <= 0:
        return image
    w, h = image.size
    longest = max(w, h)
    if longest <= max_side_px:
        return image
    scale = max_side_px / float(longest)
    return image.resize(
        (max(1, int(w * scale)), max(1, int(h * scale))),
        resample=Image.LANCZOS,
    )


def _rasterize_to_pdf(
    pdf_bytes: bytes,
    *,
    dpi: int,
    jpeg_quality: int,
    max_side_px: int,
) -> tuple[bytes, int]:
    tmp_path: str | None = None
    jpeg_paths: list[str] = []
    try:
        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.write(fd, pdf_bytes)
        os.close(fd)

        images = convert_from_path(tmp_path, fmt="jpeg", dpi=dpi)
        if not images:
            raise PodPdfOptimizeError("no pages extracted from PDF")

        for i, image in enumerate(images):
            prepared = _resize_page(image.convert("RGB"), max_side_px)
            jpeg_path = os.path.join(
                os.path.dirname(tmp_path),
                f"pod_opt_{os.getpid()}_{i:03d}.jpg",
            )
            prepared.save(
                jpeg_path,
                "JPEG",
                quality=max(25, min(95, int(jpeg_quality))),
                optimize=True,
                progressive=True,
            )
            jpeg_paths.append(jpeg_path)

        optimized = img2pdf.convert(jpeg_paths)
        return optimized, len(images)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        for path in jpeg_paths:
            if os.path.isfile(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass


def optimize_for_tms_upload(
    pdf_bytes: bytes,
    *,
    max_bytes: int,
    dpi: int = 150,
    jpeg_quality: int = 75,
    max_side_px: int = 2000,
) -> tuple[bytes, dict[str, Any]]:
    """Return PDF bytes suitable for Turvo upload; rasterize when over ``max_bytes``."""
    original_bytes = len(pdf_bytes)
    if original_bytes <= max_bytes:
        return pdf_bytes, {
            "optimized": False,
            "original_bytes": original_bytes,
            "optimized_bytes": original_bytes,
        }

    logger.info(
        "pod_pdf_optimizer: compressing PDF original_bytes=%s max_bytes=%s dpi=%s",
        original_bytes,
        max_bytes,
        dpi,
    )

    attempts = [
        (dpi, jpeg_quality, max_side_px),
        (min(120, dpi), min(60, jpeg_quality), max_side_px),
    ]
    last_size = original_bytes
    page_count = 0
    used_dpi = dpi
    used_quality = jpeg_quality

    for attempt_dpi, attempt_quality, attempt_max_side in attempts:
        used_dpi = attempt_dpi
        used_quality = attempt_quality
        candidate, page_count = _rasterize_to_pdf(
            pdf_bytes,
            dpi=attempt_dpi,
            jpeg_quality=attempt_quality,
            max_side_px=attempt_max_side,
        )
        last_size = len(candidate)
        if last_size <= max_bytes:
            logger.info(
                "pod_pdf_optimizer: compressed original_bytes=%s optimized_bytes=%s "
                "pages=%s dpi=%s quality=%s",
                original_bytes,
                last_size,
                page_count,
                attempt_dpi,
                attempt_quality,
            )
            return candidate, {
                "optimized": True,
                "original_bytes": original_bytes,
                "optimized_bytes": last_size,
                "page_count": page_count,
                "dpi": attempt_dpi,
                "jpeg_quality": attempt_quality,
                "max_side_px": attempt_max_side,
            }

    raise PodPdfOptimizeError(
        f"PDF still {last_size} bytes after optimization (limit {max_bytes}); "
        f"original {original_bytes} bytes, pages={page_count}, "
        f"dpi={used_dpi}, quality={used_quality}"
    )


__all__ = ("PodPdfOptimizeError", "optimize_for_tms_upload")
