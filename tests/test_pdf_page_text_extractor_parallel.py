"""Tests for bounded parallel OCR page fan-out in PdfPageTextExtractor."""

from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import fitz

from app.tools import pdf_page_text_extractor as mod
from app.tools.pdf_page_text_extractor import PdfPageTextExtractor


def _blank_pdf(page_count: int) -> bytes:
    doc = fitz.open()
    try:
        for _ in range(page_count):
            doc.new_page(width=612, height=792)
        return doc.tobytes()
    finally:
        doc.close()


def test_ocr_selected_pages_respects_max_workers(monkeypatch):
    monkeypatch.setattr(mod.settings, "OCR_MAX_WORKERS", 2)
    monkeypatch.setattr(mod, "_OCR_ENGINE", object())

    in_flight = 0
    max_in_flight = 0
    lock = threading.Lock()

    def fake_render(pdf_path, page_number, **kwargs):
        nonlocal in_flight, max_in_flight
        with lock:
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        image = MagicMock()
        image.mode = "RGB"
        image.size = (100, 100)
        image.crop.return_value = image
        return image

    def fake_ocr(image):
        return "text"

    extractor = PdfPageTextExtractor()
    pdf_bytes = _blank_pdf(4)

    with patch.object(mod, "render_pdf_page_image", side_effect=fake_render), patch.object(
        mod, "ocr_image_rgb", side_effect=fake_ocr
    ):
        pages = extractor.ocr_pages(
            pdf_bytes,
            page_numbers=[1, 2, 3, 4],
            header_only=False,
            doc_label="test",
        )

    assert [p.page_number for p in pages] == [1, 2, 3, 4]
    assert all(p.text == "text" and p.source == "ocr" for p in pages)
    assert max_in_flight <= 2


def test_ocr_selected_pages_single_page_stays_sequential(monkeypatch):
    monkeypatch.setattr(mod.settings, "OCR_MAX_WORKERS", 5)
    monkeypatch.setattr(mod, "_OCR_ENGINE", object())

    calls: list[int] = []

    def fake_render(pdf_path, page_number, **kwargs):
        calls.append(page_number)
        image = MagicMock()
        image.mode = "RGB"
        image.size = (100, 100)
        return image

    extractor = PdfPageTextExtractor()
    with patch.object(mod, "render_pdf_page_image", side_effect=fake_render), patch.object(
        mod, "ocr_image_rgb", return_value="only"
    ), patch.object(mod, "ThreadPoolExecutor") as pool_cls:
        pages = extractor.ocr_pages(
            _blank_pdf(1),
            page_numbers=[1],
            header_only=False,
            doc_label="test",
        )

    pool_cls.assert_not_called()
    assert calls == [1]
    assert pages[0].text == "only"


def test_header_only_uses_strip_render_kwargs(monkeypatch):
    monkeypatch.setattr(mod, "_OCR_ENGINE", object())
    seen: dict = {}

    def fake_render(pdf_path, page_number, **kwargs):
        seen.update(kwargs)
        image = MagicMock()
        image.mode = "RGB"
        image.size = (200, 50)
        return image

    extractor = PdfPageTextExtractor()
    with patch.object(mod, "render_pdf_page_image", side_effect=fake_render), patch.object(
        mod, "ocr_image_rgb", return_value="Rate confirmation"
    ):
        extractor._ocr_one_page(
            "dummy.pdf",
            1,
            header_only=True,
            doc_label="strip",
        )

    assert seen["dpi"] == mod.settings.OCR_STRIP_DPI
    assert seen["max_side_px"] == mod.settings.OCR_STRIP_IMAGE_MAX_SIDE_PX
    assert seen["header_fraction"] == mod.settings.OCR_HEADER_FRACTION
