"""Tests for load-tendering workflow state helpers."""

from __future__ import annotations

from app.domain.load_tendering_state import (
    ingest_delivery_address_code,
    ingest_pack_code,
    tender_from_ingest_row,
)


def test_tender_from_ingest_row_includes_delivery_address_code() -> None:
    row = {
        "pack_code": "5366",
        "delivery_address_code": "41000100",
        "po_number": "PO-1",
    }
    tender = tender_from_ingest_row(row, order_number="96564")
    assert tender["delivery_address_code"] == "41000100"
    assert tender["pack_code"] == "5366"


def test_ingest_delivery_address_code_prefers_nested_tender() -> None:
    data = {
        "tender": {"delivery_address_code": "111"},
        "tender_row": {"delivery_address_code": "222"},
    }
    assert ingest_delivery_address_code(data) == "111"


def test_ingest_delivery_address_code_falls_back_to_tender_row() -> None:
    data = {"tender_row": {"delivery_address_code": "222"}}
    assert ingest_delivery_address_code(data) == "222"


def test_ingest_pack_code_falls_back_to_tender_row() -> None:
    data = {"tender_row": {"pack_code": "9999"}}
    assert ingest_pack_code(data) == "9999"
