"""
OOM-safe PDF → JPEG rasterization (POD vision, ratecon vision, TMS optimize).

Cascade: direct image → embedded full-page XObjects (Tracy-class) → Poppler
page-at-a-time with MediaBox DPI clamp and a pre-convert memory budget.
Never multi-page ``convert_from_path`` in RAM; raises ``PdfTooLargeError`` first.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pdf2image import convert_from_path
from PIL import Image, UnidentifiedImageError

from app.core.config import settings

logger = logging.getLogger(__name__)

Image.MAX_IMAGE_PIXELS = settings.POD_MAX_IMAGE_PIXELS

# Letter longest side ~792pt; phone/scan PDFs that set MediaBox=pixel dims are far larger.
_PATHOLOGICAL_MEDIABOX_PT = 1200.0


class PdfTooLargeError(Exception):
    """PDF would use too much memory to convert; fail closed before OOM/SIGKILL."""

    error_key = "pdf_too_large"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


# Alias kept for POD extraction / tools that still import the old name.
PodPdfTooLargeError = PdfTooLargeError


def _safe_temp_prefix(prefix: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", (prefix or "pdf").strip())
    cleaned = (cleaned or "pdf")[:100]
    return cleaned if cleaned.endswith("_") else f"{cleaned}_"


def make_temp_pdf(
    *,
    prefix: str,
    directory: str | Path | None = None,
) -> tuple[int, str]:
    """
    Create an empty temp PDF path with a meaningful ``prefix`` (still unique).

    When ``directory`` is set (e.g. ``RATECON_STAGE_ROOT`` / ``POD_ATTACHMENT_STAGE_ROOT``),
    the file is created there instead of the OS default temp dir.
    """
    if directory is not None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return tempfile.mkstemp(
            prefix=_safe_temp_prefix(prefix),
            suffix=".pdf",
            dir=str(directory),
        )
    return tempfile.mkstemp(prefix=_safe_temp_prefix(prefix), suffix=".pdf")


def make_temp_workdir(*, prefix: str, directory: str | Path | None = None) -> str:
    """Create a temp directory under ``directory`` (or OS temp) for raster page JPEGs."""
    if directory is not None:
        Path(directory).mkdir(parents=True, exist_ok=True)
        return tempfile.mkdtemp(prefix=_safe_temp_prefix(prefix), dir=str(directory))
    return tempfile.mkdtemp(prefix=_safe_temp_prefix(prefix))


def freightx_stage_dir(root: str, name: str) -> Path:
    """``{root}/{sanitized_name}/`` — same layout style as POD attachment staging."""
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", (name or "doc").strip())
    cleaned = (cleaned or "doc")[:120]
    path = Path(root) / cleaned
    path.mkdir(parents=True, exist_ok=True)
    return path


def _pdf_name(pdf_path: str) -> str:
    """Basename of the PDF path without extension (for log lines)."""
    return Path(pdf_path).stem.replace(" POD", "").strip() or "document"


@dataclass(frozen=True)
class PdfRasterOptions:
    dpi: int = 200
    max_side_px: int = 0
    jpeg_quality: int = 85
    max_pages: int | None = None
    max_page_bytes: int = 0
    max_total_bytes: int = 0
    thread_count: int = 1

    def resolved(self) -> PdfRasterOptions:
        return PdfRasterOptions(
            dpi=int(self.dpi) if self.dpi else settings.POD_IMAGE_DPI,
            max_side_px=(
                int(self.max_side_px)
                if self.max_side_px and self.max_side_px > 0
                else settings.POD_IMAGE_MAX_SIDE_PX
            ),
            jpeg_quality=(
                int(self.jpeg_quality)
                if self.jpeg_quality
                else settings.POD_JPEG_QUALITY
            ),
            max_pages=self.max_pages,
            max_page_bytes=(
                int(self.max_page_bytes)
                if self.max_page_bytes and self.max_page_bytes > 0
                else settings.POD_CONVERT_MAX_PAGE_BYTES
            ),
            max_total_bytes=(
                int(self.max_total_bytes)
                if self.max_total_bytes and self.max_total_bytes > 0
                else settings.POD_CONVERT_MAX_TOTAL_BYTES
            ),
            thread_count=1,  # never parallelize Poppler in-process
        )


def _resize_for_vision(image: Image.Image, max_side_px: int) -> Image.Image:
    """Downscale image so the longest side is <= max_side_px (keeps aspect ratio)."""
    if not max_side_px or max_side_px <= 0:
        return image
    w, h = image.size
    longest = max(w, h)
    if longest <= max_side_px:
        return image
    scale = max_side_px / float(longest)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return image.resize((new_w, new_h), resample=Image.LANCZOS)


def _rgb_bytes(width: int, height: int) -> int:
    return max(0, int(width)) * max(0, int(height)) * 3


def _save_jpeg(
    image: Image.Image,
    image_path: str,
    *,
    max_side_px: int,
    jpeg_quality: int,
) -> None:
    prepared = _resize_for_vision(image.convert("RGB"), max_side_px=max_side_px)
    prepared.save(
        image_path,
        "JPEG",
        quality=max(25, min(95, int(jpeg_quality))),
        optimize=True,
        progressive=True,
    )


def _page_mediabox_pts(page: Any) -> tuple[float, float]:
    box = page.mediabox
    return float(box[2] - box[0]), float(box[3] - box[1])


def _is_pathological_mediabox(width_pt: float, height_pt: float) -> bool:
    return max(width_pt, height_pt) >= _PATHOLOGICAL_MEDIABOX_PT


def _effective_poppler_dpi(
    *,
    requested_dpi: int,
    width_pt: float,
    height_pt: float,
) -> int:
    """
    For phone/scanner PDFs that set MediaBox = pixel size in points, DPI>72
    upscales inventively (e.g. 200/72 ≈ 2.78× per side). Use 72 DPI then.
    """
    if _is_pathological_mediabox(width_pt, height_pt):
        return min(int(requested_dpi), 72)
    return int(requested_dpi)


def _assert_conversion_memory_budget(
    *,
    page_bytes: int,
    total_bytes: int,
    page_number: int,
    max_page_bytes: int,
    max_total_bytes: int,
) -> None:
    if max_page_bytes > 0 and page_bytes > max_page_bytes:
        raise PdfTooLargeError(
            f"page {page_number} conversion memory estimate {page_bytes} bytes exceeds "
            f"POD_CONVERT_MAX_PAGE_BYTES={max_page_bytes}"
        )
    if max_total_bytes > 0 and total_bytes > max_total_bytes:
        raise PdfTooLargeError(
            f"total conversion memory estimate {total_bytes} bytes exceeds "
            f"POD_CONVERT_MAX_TOTAL_BYTES={max_total_bytes}"
        )


def _try_extract_embedded_page_images(
    pdf_path: str,
    temp_dir: str,
    *,
    max_side_px: int,
    jpeg_quality: int,
    max_pages: int | None,
    max_page_bytes: int,
    max_total_bytes: int,
) -> list[str] | None:
    """
    If every page is a single full-page image XObject (Tracy-class phone/scan PDF),
    extract those images without Poppler MediaBox upscaling. Returns None to fall back.
    """
    try:
        import pikepdf
        from pikepdf import PdfImage
    except ImportError:
        return None

    try:
        with pikepdf.open(pdf_path) as pdf:
            pages = list(pdf.pages)
            if max_pages and max_pages > 0:
                pages = pages[:max_pages]
            if not pages:
                return None

            extracted: list[tuple[int, Any]] = []
            total_bytes = 0
            for index, page in enumerate(pages, start=1):
                images = page.get_images()
                items = list(images.items())
                if len(items) != 1:
                    return None
                _name, obj = items[0]
                pdf_image = PdfImage(obj)
                width_pt, height_pt = _page_mediabox_pts(page)
                # Phone/scan pattern: MediaBox points == image pixel dimensions.
                if (
                    abs(pdf_image.width - width_pt) > max(2.0, 0.05 * width_pt)
                    or abs(pdf_image.height - height_pt) > max(2.0, 0.05 * height_pt)
                ):
                    return None
                page_bytes = _rgb_bytes(pdf_image.width, pdf_image.height)
                total_bytes += page_bytes
                _assert_conversion_memory_budget(
                    page_bytes=page_bytes,
                    total_bytes=total_bytes,
                    page_number=index,
                    max_page_bytes=max_page_bytes,
                    max_total_bytes=max_total_bytes,
                )
                extracted.append((index, pdf_image))

            image_paths: list[str] = []
            for index, pdf_image in extracted:
                image_path = os.path.join(temp_dir, f"page_{index:03d}.jpg")
                pil_image = pdf_image.as_pil_image()
                _save_jpeg(
                    pil_image,
                    image_path,
                    max_side_px=max_side_px,
                    jpeg_quality=jpeg_quality,
                )
                image_paths.append(image_path)

            logger.info(
                "pdf_raster: using embedded page images pdf_name=%s page_count=%s",
                _pdf_name(pdf_path),
                len(image_paths),
            )
            return image_paths
    except PdfTooLargeError:
        raise
    except Exception:
        logger.info(
            "pdf_raster: embedded page image path unavailable; falling back to Poppler",
            exc_info=True,
        )
        return None


def _convert_one_page(
    pdf_path: str,
    *,
    page_number: int,
    dpi: int,
) -> Image.Image | None:
    images = convert_from_path(
        pdf_path,
        fmt="jpeg",
        dpi=dpi,
        thread_count=1,
        first_page=page_number,
        last_page=page_number,
    )
    if not images:
        return None
    return images[0]


def _convert_pdf_with_poppler_page_at_a_time(
    pdf_path: str,
    temp_dir: str,
    *,
    dpi: int,
    max_side_px: int,
    jpeg_quality: int,
    max_pages: int | None,
    max_page_bytes: int,
    max_total_bytes: int,
) -> list[str]:
    """Rasterize one page at a time; adjust DPI for pathological MediaBox PDFs."""
    try:
        from pdf2image import pdfinfo_from_path
    except Exception:
        pdfinfo_from_path = None  # type: ignore[assignment]

    page_count: int | None = None
    mediaboxes: list[tuple[float, float]] = []
    try:
        import pikepdf

        with pikepdf.open(pdf_path) as pdf:
            pages = list(pdf.pages)
            if max_pages and max_pages > 0:
                pages = pages[:max_pages]
            page_count = len(pages)
            mediaboxes = [_page_mediabox_pts(page) for page in pages]
    except Exception:
        mediaboxes = []
        if pdfinfo_from_path is not None:
            try:
                info = pdfinfo_from_path(pdf_path)
                page_count = int(info.get("Pages") or 0) or None
                if max_pages and max_pages > 0 and page_count:
                    page_count = min(page_count, max_pages)
            except Exception:
                page_count = None

    # Unknown page count: walk page-at-a-time until empty (never multi-page in RAM).
    if page_count is None or page_count < 1:
        image_paths: list[str] = []
        total_bytes = 0
        hard_cap = max_pages if max_pages and max_pages > 0 else 500
        for page_number in range(1, hard_cap + 1):
            image = _convert_one_page(pdf_path, page_number=page_number, dpi=dpi)
            if image is None:
                break
            page_bytes = _rgb_bytes(*image.size)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=page_number,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
            image_path = os.path.join(temp_dir, f"page_{page_number:03d}.jpg")
            _save_jpeg(
                image,
                image_path,
                max_side_px=max_side_px,
                jpeg_quality=jpeg_quality,
            )
            image_paths.append(image_path)
            del image
        if not image_paths:
            raise ValueError(f"No images could be extracted from PDF: {pdf_path}")
        return image_paths

    if max_pages and max_pages > 0:
        page_count = min(page_count, max_pages)

    image_paths = []
    total_bytes = 0
    for page_number in range(1, page_count + 1):
        if mediaboxes and page_number <= len(mediaboxes):
            width_pt, height_pt = mediaboxes[page_number - 1]
            page_dpi = _effective_poppler_dpi(
                requested_dpi=dpi,
                width_pt=width_pt,
                height_pt=height_pt,
            )
            est_w = int(width_pt * page_dpi / 72.0)
            est_h = int(height_pt * page_dpi / 72.0)
            page_bytes = _rgb_bytes(est_w, est_h)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=page_number,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
        else:
            page_dpi = dpi

        image = _convert_one_page(pdf_path, page_number=page_number, dpi=page_dpi)
        if image is None:
            raise ValueError(
                f"No image extracted from PDF page {page_number}: {pdf_path}"
            )
        if not mediaboxes:
            page_bytes = _rgb_bytes(*image.size)
            total_bytes += page_bytes
            _assert_conversion_memory_budget(
                page_bytes=page_bytes,
                total_bytes=total_bytes,
                page_number=page_number,
                max_page_bytes=max_page_bytes,
                max_total_bytes=max_total_bytes,
            )
        image_path = os.path.join(temp_dir, f"page_{page_number:03d}.jpg")
        _save_jpeg(
            image,
            image_path,
            max_side_px=max_side_px,
            jpeg_quality=jpeg_quality,
        )
        image_paths.append(image_path)
        del image

    return image_paths


def rasterize_pdf_to_jpeg_paths(
    pdf_path: str,
    output_dir: str,
    options: PdfRasterOptions | None = None,
) -> list[str]:
    """
    Rasterize ``pdf_path`` to JPEGs under ``output_dir``.

    Flow: try as a single image → embedded page images → Poppler one page at a time.
    Raises ``PdfTooLargeError`` when the memory budget would be exceeded.
    """
    opts = (options or PdfRasterOptions()).resolved()
    pdf_name = _pdf_name(pdf_path)
    os.makedirs(output_dir, exist_ok=True)

    logger.info(
        "pdf_raster: preparing document for raster pdf_path=%s pdf_name=%s dpi=%s",
        pdf_path,
        pdf_name,
        opts.dpi,
    )

    try:
        try:
            with Image.open(pdf_path) as image:
                if str(getattr(image, "format", "")).upper() not in {
                    "JPEG",
                    "JPG",
                    "PNG",
                    "GIF",
                    "WEBP",
                    "BMP",
                    "TIFF",
                }:
                    raise UnidentifiedImageError(
                        f"Unsupported direct image format: {getattr(image, 'format', None)}"
                    )
                image.load()
                image_path = os.path.join(output_dir, "page_001.jpg")
                _save_jpeg(
                    image,
                    image_path,
                    max_side_px=opts.max_side_px,
                    jpeg_quality=opts.jpeg_quality,
                )
                logger.info(
                    "pdf_raster: image attachment prepared pdf_name=%s path=%s",
                    pdf_name,
                    image_path,
                )
                return [image_path]
        except (UnidentifiedImageError, OSError, ValueError):
            pass

        embedded = _try_extract_embedded_page_images(
            pdf_path,
            output_dir,
            max_side_px=opts.max_side_px,
            jpeg_quality=opts.jpeg_quality,
            max_pages=opts.max_pages,
            max_page_bytes=opts.max_page_bytes,
            max_total_bytes=opts.max_total_bytes,
        )
        if embedded:
            return embedded

        image_paths = _convert_pdf_with_poppler_page_at_a_time(
            pdf_path,
            output_dir,
            dpi=opts.dpi,
            max_side_px=opts.max_side_px,
            jpeg_quality=opts.jpeg_quality,
            max_pages=opts.max_pages,
            max_page_bytes=opts.max_page_bytes,
            max_total_bytes=opts.max_total_bytes,
        )
        logger.info(
            "pdf_raster: PDF conversion successful pdf_name=%s page_count=%s",
            pdf_name,
            len(image_paths),
        )
        return image_paths
    except PdfTooLargeError:
        logger.warning(
            "pdf_raster: PDF too large to convert pdf_name=%s pdf_path=%s",
            pdf_name,
            pdf_path,
        )
        raise
    except Exception as e:
        error_msg = f"Failed to convert PDF to images: {type(e).__name__}: {str(e)}"
        logger.exception("pdf_raster: PDF conversion failed pdf_path=%s", pdf_path)
        raise Exception(error_msg) from e


__all__ = (
    "PdfRasterOptions",
    "PdfTooLargeError",
    "PodPdfTooLargeError",
    "_effective_poppler_dpi",
    "_try_extract_embedded_page_images",
    "freightx_stage_dir",
    "make_temp_pdf",
    "make_temp_workdir",
    "rasterize_pdf_to_jpeg_paths",
)
