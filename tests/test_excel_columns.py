"""Tests for Excel column letter helpers."""

from __future__ import annotations

from typing import Any

from app.domain.excel_columns import cell_at_column_index, excel_column_to_zero_based


def test_excel_column_to_zero_based() -> None:
    assert excel_column_to_zero_based("A") == 0
    assert excel_column_to_zero_based("B") == 1
    assert excel_column_to_zero_based("J") == 9
    assert excel_column_to_zero_based("BJ") == 61


def test_cell_at_column_index() -> None:
    row: dict[str, Any] = {"c0": "a", "c1": "b", "c2": "c"}
    assert cell_at_column_index(row, 0) == "a"
    assert cell_at_column_index(row, 1) == "b"
    assert cell_at_column_index(row, 99) is None
    assert cell_at_column_index(row, -1) is None


def test_cell_at_column_index_jsonb_reordered_keys() -> None:
    """jsonb sorts keys lexicographically; explicit index lookup must still read C and J."""
    row: dict[str, Any] = {
        "0": 200,
        "1": 44225600,
        "10": None,
        "11": "233 E. BRISTOL LANE",
        "2": 44225600,
        "9": "MERICAL",
    }
    assert cell_at_column_index(row, 2) == 44225600
    assert cell_at_column_index(row, 9) == "MERICAL"
