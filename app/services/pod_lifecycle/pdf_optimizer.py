"""Compress large POD PDFs before Turvo TMS upload (10 MB API limit)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

import img2pdf

from app.core.logger import get_logger
from app.tools.pdf_raster import (
    PdfRasterOptions,
    PdfTooLargeError,
    make_temp_pdf,
    rasterize_pdf_to_jpeg_paths,
)

logger = get_logger(__name__)


class PodPdfOptimizeError(Exception):
    """Raised when a PDF cannot be reduced below the TMS upload size limit."""


def _rasterize_to_pdf(
    pdf_bytes: bytes,
    *,
    dpi: int,
    jpeg_quality: int,
    max_side_px: int,
    doc_label: str,
) -> tuple[bytes, int]:
    """Rasterize via shared pdf_raster, then rebuild a PDF with img2pdf."""
    tmp_path: str | None = None
    work_dir: str | None = None
    try:
        fd, tmp_path = make_temp_pdf(prefix=doc_label)
        os.write(fd, pdf_bytes)
        os.close(fd)

        work_dir = tempfile.mkdtemp(prefix=f"{doc_label}_raster_")
        jpeg_paths = rasterize_pdf_to_jpeg_paths(
            tmp_path,
            work_dir,
            PdfRasterOptions(
                dpi=dpi,
                max_side_px=max_side_px,
                jpeg_quality=jpeg_quality,
            ),
        )
        if not jpeg_paths:
            raise PodPdfOptimizeError("no pages extracted from PDF")

        optimized = img2pdf.convert(jpeg_paths)
        return optimized, len(jpeg_paths)
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if work_dir and os.path.isdir(work_dir):
            for name in os.listdir(work_dir):
                path = os.path.join(work_dir, name)
                try:
                    os.unlink(path)
                except OSError:
                    pass
            try:
                os.rmdir(work_dir)
            except OSError:
                pass


def optimize_for_tms_upload(
    pdf_bytes: bytes,
    *,
    max_bytes: int,
    dpi: int = 150,
    jpeg_quality: int = 75,
    max_side_px: int = 2000,
    shipment_id: str | None = None,
) -> tuple[bytes, dict[str, Any]]:
    """
    Return PDF bytes suitable for Turvo upload; rasterize when over ``max_bytes``.

    Uses the shared OOM-safe rasterizer. Memory-budget trips raise
    ``PdfTooLargeError`` (fail closed — no unsafe all-pages rasterization).
    """
    original_bytes = len(pdf_bytes)
    if original_bytes <= max_bytes:
        return pdf_bytes, {
            "optimized": False,
            "original_bytes": original_bytes,
            "optimized_bytes": original_bytes,
        }

    ship = str(shipment_id or "").strip() or "unknown"
    doc_label = f"pod_tms_{ship}"

    logger.info(
        "pod_pdf_optimizer: compressing PDF original_bytes=%s max_bytes=%s dpi=%s "
        "shipment_id=%s",
        original_bytes,
        max_bytes,
        dpi,
        ship,
    )

    # Two quality/DPI steps only; both stay on the safe page-at-a-time path.
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
        try:
            candidate, page_count = _rasterize_to_pdf(
                pdf_bytes,
                dpi=attempt_dpi,
                jpeg_quality=attempt_quality,
                max_side_px=attempt_max_side,
                doc_label=doc_label,
            )
        except PdfTooLargeError:
            logger.warning(
                "pod_pdf_optimizer: PDF too large to rasterize safely "
                "original_bytes=%s dpi=%s shipment_id=%s",
                original_bytes,
                attempt_dpi,
                ship,
            )
            raise
        last_size = len(candidate)
        if last_size <= max_bytes:
            logger.info(
                "pod_pdf_optimizer: compressed original_bytes=%s optimized_bytes=%s "
                "pages=%s dpi=%s quality=%s shipment_id=%s",
                original_bytes,
                last_size,
                page_count,
                attempt_dpi,
                attempt_quality,
                ship,
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


__all__ = ("PodPdfOptimizeError", "PdfTooLargeError", "optimize_for_tms_upload")
