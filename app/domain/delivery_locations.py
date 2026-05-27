"""Helpers for Delivery locations sheet rows (SharePoint .xlsx export)."""

from __future__ import annotations

import math
import re
from typing import Any

from app.domain.spreadsheet_cells import identifier_string_from_cell

# Sheet column name (typo preserved to match source data).
DELIVERY_NUMBER_FIELD = "delviery"


def clean_cell_value(value: Any) -> Any:
    """Strip padding, collapse whitespace, and normalize missing cells to ``None``.

    pandas hands blank xlsx cells back as ``float('nan')``; without this, the
    NaN floats end up in ``delivery_address`` as the literal string ``"nan"``
    once they pass through ``str(...)``.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, str):
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned or cleaned.lower() == "nan":
            return None
        return cleaned
    return value


def normalize_delivery_number(value: Any) -> str | None:
    """Normalize a delivery number for lookup (same rules as cell cleaning)."""
    cleaned = clean_cell_value(value)
    if cleaned is None:
        return None
    return identifier_string_from_cell(cleaned)


def clean_row(row: dict[str, Any]) -> dict[str, Any]:
    return {key: clean_cell_value(val) for key, val in row.items()}


def clean_delivery_locations_sheet(sheet: dict[str, Any]) -> dict[str, Any]:
    rows = sheet.get("rows") or []
    cleaned_rows = [
        clean_row(row) for row in rows if isinstance(row, dict)
    ]
    return {
        **sheet,
        "rows": cleaned_rows,
        "row_count": len(cleaned_rows),
    }


class DeliveryLocationsIndex:
    """In-memory index of Delivery locations rows keyed by normalized ``delviery``."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._by_delivery_number = self.build_index(rows)

    @staticmethod
    def build_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            cleaned = clean_row(row)
            key = normalize_delivery_number(cleaned.get(DELIVERY_NUMBER_FIELD))
            if key and key not in index:
                index[key] = cleaned
        return index

    def lookup(self, delivery_number: str) -> dict[str, Any] | None:
        key = normalize_delivery_number(delivery_number)
        if not key:
            return None
        return self._by_delivery_number.get(key)
