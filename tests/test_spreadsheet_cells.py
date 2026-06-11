"""Tests for Excel cell identifier normalization."""

from __future__ import annotations

from app.domain.delivery_locations import normalize_delivery_number
from app.domain.load_tendering_tender_rows import projected_row_to_tender_insert
from app.domain.spreadsheet_cells import identifier_string_from_cell


def test_identifier_string_from_cell_strips_excel_float_suffix() -> None:
    assert identifier_string_from_cell(93384.0) == "93384"
    assert identifier_string_from_cell("93384.0") == "93384"
    assert identifier_string_from_cell(93384) == "93384"


def test_identifier_string_from_cell_preserves_non_integer_values() -> None:
    assert identifier_string_from_cell("PO-1") == "PO-1"
    assert identifier_string_from_cell(12.5) == "12.5"


def test_identifier_string_from_cell_blank_and_nan() -> None:
    assert identifier_string_from_cell(None) is None
    assert identifier_string_from_cell(float("nan")) is None
    assert identifier_string_from_cell("  ") is None


def test_projected_row_order_number_without_decimal_suffix() -> None:
    row = {
        "order_number": 93795.0,
        "customer_match": "Acme",
        "weight_unit": "KG",
        "po_number": 4500123456.0,
    }
    out = projected_row_to_tender_insert(row, customer_name="Acme")
    assert out is not None
    assert out["order_number"] == "93795"
    assert out["metadata"] == {"po_number": "4500123456"}


def test_normalize_delivery_number_without_decimal_suffix() -> None:
    assert normalize_delivery_number(41000100.0) == "41000100"
    assert normalize_delivery_number("41000100.0") == "41000100"
