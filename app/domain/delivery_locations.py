"""Helpers for Delivery locations sheet rows (SharePoint .xlsx export)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.spreadsheet_cells import clean_cell_value, identifier_string_from_cell

if TYPE_CHECKING:
    from app.domain.delivery_locations_column_mapping import (
        DeliveryLocationsColumnMapping,
    )

# Sheet column name (typo preserved to match source data).
DELIVERY_NUMBER_FIELD = "delviery"


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


def _sheet_has_data_rows(sheet: dict[str, Any]) -> bool:
    rows = sheet.get("rows")
    if not isinstance(rows, list) or not rows:
        return False
    return any(isinstance(r, dict) for r in rows)


def select_delivery_locations_sheet(
    sheets: list[dict[str, Any]],
    *,
    preferred_tab_name: str | None = None,
) -> dict[str, Any] | None:
    """
    Pick the delivery-locations data sheet from an already-identified workbook.

    The workbook is scoped by filename (``delivery_location.xlsx``) before this runs.
    ``preferred_tab_name`` is an optional hint (case-insensitive); otherwise the
    first non-empty sheet is used.
    """
    candidates = [s for s in sheets if isinstance(s, dict) and _sheet_has_data_rows(s)]
    if not candidates:
        return None

    hint = (preferred_tab_name or "").strip()
    if hint:
        hint_lower = hint.casefold()
        for sheet in candidates:
            name = sheet.get("name")
            if name is not None and str(name).strip().casefold() == hint_lower:
                return sheet

    return candidates[0]


class DeliveryLocationsIndex:
    """In-memory index of Delivery locations rows keyed by normalized ``delviery``."""

    def __init__(
        self,
        rows: list[dict[str, Any]],
        *,
        column_mapping: DeliveryLocationsColumnMapping | None = None,
    ) -> None:
        self._by_delivery_number = self.build_index(
            rows, column_mapping=column_mapping
        )

    @staticmethod
    def build_index(
        rows: list[dict[str, Any]],
        *,
        column_mapping: DeliveryLocationsColumnMapping | None = None,
    ) -> dict[str, dict[str, Any]]:
        index: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            if column_mapping is not None:
                cleaned = column_mapping.materialize_row(row)
            else:
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
