"""Tests for LLM-driven RATE_CONFIRMATION page trim (RateconPageTrimService)."""

from __future__ import annotations

import io
from pathlib import Path

import pikepdf

from app.services.pod_lifecycle.ratecon_page_trim import (
    RateconPageTrimService,
    collect_ratecon_page_numbers,
)


def _pdf_with_pages(n: int) -> bytes:
    pdf = pikepdf.Pdf.new()
    for _ in range(n):
        pdf.add_blank_page()
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def test_collect_ratecon_page_numbers_ok():
    pages = [
        {"page_number": 1, "page_type": "BILL_OF_LADING"},
        {"page_number": 2, "page_type": "RATE_CONFIRMATION"},
        {"page_number": 3, "page_type": "rate_confirmation"},
    ]
    nums, err = collect_ratecon_page_numbers(pages)
    assert err is None
    assert nums == [2, 3]


def test_collect_ratecon_page_numbers_malformed():
    nums, err = collect_ratecon_page_numbers(None)
    assert nums is None
    assert err == "pages_unusable"
    nums, err = collect_ratecon_page_numbers([{"page_number": "1"}])
    assert nums is None
    assert err == "pages_unusable"


def test_trim_local_pdf_writes_trimmed_and_only_ratecon(tmp_path):
    merged = tmp_path / "pod_SHIP.pdf"
    merged.write_bytes(_pdf_with_pages(2))
    svc = RateconPageTrimService()

    cont = svc.trim_local_pdf(
        merged_local_path=str(merged),
        pages=[
            {"page_number": 1, "page_type": "BILL_OF_LADING"},
            {"page_number": 2, "page_type": "RATE_CONFIRMATION"},
        ],
        stage_dir=str(tmp_path),
        shipment_number="SHIP",
    )
    assert cont.outcome == "continue"
    assert cont.error is None
    assert cont.trimmed_local_path
    assert cont.excluded_page_numbers == [2]
    assert Path(cont.trimmed_local_path).is_file()

    only = svc.trim_local_pdf(
        merged_local_path=str(merged),
        pages=[
            {"page_number": 1, "page_type": "RATE_CONFIRMATION"},
            {"page_number": 2, "page_type": "RATE_CONFIRMATION"},
        ],
        stage_dir=str(tmp_path),
        shipment_number="SHIP",
    )
    assert only.outcome == "only_ratecon"
    assert only.kept_page_count == 0
    assert only.trimmed_local_path is None
