"""Excel column letter helpers for positional spreadsheet row access."""

from __future__ import annotations

from typing import Any, Mapping

from openpyxl.utils.cell import column_index_from_string


def excel_column_to_zero_based(letters: str) -> int:
    """Convert Excel column letters (e.g. ``B``, ``BJ``) to a 0-based index."""
    return column_index_from_string(letters.strip().upper()) - 1


def cell_at_column_index(row: Mapping[str, Any], zero_based_index: int) -> Any:
    """
    Return the cell at ``zero_based_index`` in a headerless spreadsheet row.

    Prefer explicit positional keys (``0`` / ``"0"``) so reads stay correct after
    PostgreSQL ``jsonb`` reorders object keys. Fall back to insertion-order values
    for legacy test rows (``c0``, ``c1``, …).
    """
    if zero_based_index < 0:
        return None
    for key in (zero_based_index, str(zero_based_index)):
        if key in row:
            return row[key]
    legacy = f"c{zero_based_index}"
    if legacy in row:
        return row[legacy]
    values = list(row.values())
    if zero_based_index >= len(values):
        return None
    return values[zero_based_index]
