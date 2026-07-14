"""Tests for app.services.pod_lifecycle.pdf_optimizer."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import patch

import img2pdf
import pytest
from PIL import Image

from app.services.pod_lifecycle.pdf_optimizer import (
    PodPdfOptimizeError,
    optimize_for_tms_upload,
)
from app.tools.pdf_raster import PdfTooLargeError

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"


def _large_pdf_bytes(pages: int = 3, size: tuple[int, int] = (4000, 5000)) -> bytes:
    images = []
    for _ in range(pages):
        img = Image.new("RGB", size, color=(200, 100, 50))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=95)
        images.append(buf.getvalue())
    return img2pdf.convert(images)


def test_optimize_passthrough_when_under_limit():
    pdf = _MIN_PDF
    out, meta = optimize_for_tms_upload(pdf, max_bytes=len(pdf) + 100)
    assert out == pdf
    assert meta["optimized"] is False
    assert meta["original_bytes"] == len(pdf)


def test_optimize_compresses_oversized_pdf(tmp_path: Path):
    large = _large_pdf_bytes(pages=2)
    assert len(large) > 50_000

    jpeg_a = tmp_path / "page_001.jpg"
    jpeg_b = tmp_path / "page_002.jpg"
    Image.new("RGB", (800, 1000), color=(255, 255, 255)).save(jpeg_a, "JPEG")
    Image.new("RGB", (800, 1000), color=(255, 255, 255)).save(jpeg_b, "JPEG")

    with patch(
        "app.services.pod_lifecycle.pdf_optimizer.rasterize_pdf_to_jpeg_paths",
        return_value=[str(jpeg_a), str(jpeg_b)],
    ):
        out, meta = optimize_for_tms_upload(
            large,
            max_bytes=50_000,
            dpi=150,
            jpeg_quality=75,
            max_side_px=1200,
        )

    assert meta["optimized"] is True
    assert len(out) <= 50_000
    assert meta["optimized_bytes"] == len(out)
    assert meta["page_count"] == 2


def test_optimize_raises_when_still_too_large(tmp_path: Path):
    large = _large_pdf_bytes(pages=1)
    tiny_limit = 100
    jpeg = tmp_path / "page_001.jpg"
    Image.new("RGB", (2000, 2000), color=(0, 0, 0)).save(jpeg, "JPEG")

    with patch(
        "app.services.pod_lifecycle.pdf_optimizer.rasterize_pdf_to_jpeg_paths",
        return_value=[str(jpeg)],
    ), patch(
        "app.services.pod_lifecycle.pdf_optimizer.img2pdf.convert",
        return_value=b"x" * 500,
    ):
        with pytest.raises(PodPdfOptimizeError):
            optimize_for_tms_upload(large, max_bytes=tiny_limit)


def test_optimize_raises_pdf_too_large_when_budget_trips():
    large = _large_pdf_bytes(pages=1)
    with patch(
        "app.services.pod_lifecycle.pdf_optimizer.rasterize_pdf_to_jpeg_paths",
        side_effect=PdfTooLargeError("over budget"),
    ):
        with pytest.raises(PdfTooLargeError):
            optimize_for_tms_upload(large, max_bytes=50_000)


@pytest.mark.slow
def test_optimize_pod_30389_fixture_under_10mb():
    fixture = Path(__file__).resolve().parent / "fixtures" / "pod_30389.pdf"
    if not fixture.is_file():
        pytest.skip("pod_30389.pdf fixture not present")

    pdf_bytes = fixture.read_bytes()
    assert len(pdf_bytes) > 10 * 1024 * 1024

    out, meta = optimize_for_tms_upload(
        pdf_bytes,
        max_bytes=10 * 1024 * 1024,
        dpi=150,
        jpeg_quality=75,
        max_side_px=2000,
    )

    assert meta["optimized"] is True
    assert len(out) <= 10 * 1024 * 1024
