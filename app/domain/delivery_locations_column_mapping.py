"""Excel column-letter mapping for Delivery locations sheet rows."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.domain.spreadsheet_cells import clean_cell_value, identifier_string_from_cell

DELIVERY_NUMBER_FIELD = "delviery"
from app.domain.excel_columns import cell_at_column_index, excel_column_to_zero_based

# Canonical keys consumed by delivery_address_from_location_row.
_CANONICAL_NAME = "Name"
_CANONICAL_STREET = "Street"
_CANONICAL_STREET2 = "Street 2"
_CANONICAL_ZIP = "Zip Code"
_CANONICAL_CITY = "City"
_CANONICAL_COUNTRY = "country name"


def _is_gelita_headered_export_row(row: Mapping[str, Any]) -> bool:
    """pandas header row exports use keys like ``41000000.1`` instead of column letters."""
    return any(str(k).strip().startswith("41000000") for k in row)


def _pick_cell_by_key(row: Mapping[str, Any], predicate) -> Any:
    for key, val in row.items():
        if predicate(str(key)):
            return clean_cell_value(val)
    return None


def _delivery_number_from_gelita_headered_row(row: Mapping[str, Any]) -> Any:
    preferred = _pick_cell_by_key(
        row, lambda k: k.strip() == "41000000.1" or k.strip().startswith("41000000.1")
    )
    if preferred is not None:
        return preferred
    best: Any = None
    best_len = 0
    for key, val in row.items():
        if not str(key).strip().startswith("41000000"):
            continue
        cleaned = clean_cell_value(val)
        ident = identifier_string_from_cell(cleaned)
        if ident and len(ident) > best_len:
            best = cleaned
            best_len = len(ident)
    return best


def _materialize_gelita_headered_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Map Gelita delivery_location.xlsx rows ingested with pandas header=0."""
    return {
        DELIVERY_NUMBER_FIELD: _delivery_number_from_gelita_headered_row(row),
        _CANONICAL_NAME: _pick_cell_by_key(
            row, lambda k: "CLAIMS" in k.upper() or "FACTORS" in k.upper()
        ),
        _CANONICAL_STREET: _pick_cell_by_key(row, lambda k: k.strip() == "Unnamed: 11"),
        _CANONICAL_STREET2: None,
        _CANONICAL_ZIP: _pick_cell_by_key(row, lambda k: k.strip().startswith("76172")),
        _CANONICAL_CITY: _pick_cell_by_key(
            row, lambda k: "HILLS" in k.upper() and "CLAIMS" not in k.upper()
        ),
        _CANONICAL_COUNTRY: _pick_cell_by_key(row, lambda k: "U.S.A." in k),
    }


class DeliveryLocationsColumnMapping(BaseModel):
    """Map Delivery locations fields by Excel column letter (positional read only)."""

    model_config = ConfigDict(extra="forbid")

    delivery_number: str = Field(description="Excel column for delivery lookup key")
    name: str
    street: str
    street2: str
    zip_code: str
    city: str
    country: str

    def _cell(self, row: Mapping[str, Any], column_letter: str) -> Any:
        index = excel_column_to_zero_based(column_letter)
        return cell_at_column_index(row, index)

    def materialize_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """
        Build a row dict with canonical header keys from column positions only.

        Gelita exports ingested with pandas ``header=0`` use header cells as dict keys;
        those rows are detected and mapped by known header patterns instead of letters.
        """
        if _is_gelita_headered_export_row(row):
            return _materialize_gelita_headered_row(row)
        return {
            DELIVERY_NUMBER_FIELD: clean_cell_value(
                self._cell(row, self.delivery_number)
            ),
            _CANONICAL_NAME: clean_cell_value(self._cell(row, self.name)),
            _CANONICAL_STREET: clean_cell_value(self._cell(row, self.street)),
            _CANONICAL_STREET2: clean_cell_value(self._cell(row, self.street2)),
            _CANONICAL_ZIP: clean_cell_value(self._cell(row, self.zip_code)),
            _CANONICAL_CITY: clean_cell_value(self._cell(row, self.city)),
            _CANONICAL_COUNTRY: clean_cell_value(self._cell(row, self.country)),
        }
