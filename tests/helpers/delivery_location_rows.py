"""Test helpers for Delivery locations wide Excel rows."""

from __future__ import annotations

from typing import Any

from app.domain.excel_columns import excel_column_to_zero_based


def row_with_cells(**at_letter: Any) -> dict[str, Any]:
    """Build an ordered row dict with values at Excel column letters."""
    max_i = max(excel_column_to_zero_based(k) for k in at_letter)
    values: list[Any] = [None] * (max_i + 1)
    for letter, val in at_letter.items():
        values[excel_column_to_zero_based(letter)] = val
    return {f"c{i}": v for i, v in enumerate(values)}
