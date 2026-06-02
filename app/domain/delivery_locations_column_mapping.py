"""Excel column-letter and optional header mapping for Delivery locations rows."""

from __future__ import annotations

from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field

from app.domain.delivery_locations import clean_row
from app.domain.excel_columns import cell_at_column_index, excel_column_to_zero_based
from app.domain.spreadsheet_cells import clean_cell_value, identifier_string_from_cell

DELIVERY_NUMBER_FIELD = "delviery"

# Canonical keys consumed by delivery_address_from_location_row.
_CANONICAL_NAME = "Name"
_CANONICAL_STREET = "Street"
_CANONICAL_STREET2 = "Street 2"
_CANONICAL_ZIP = "Zip Code"
_CANONICAL_CITY = "City"
_CANONICAL_COUNTRY = "country name"

_DELIVERY_NUMBER_ALIASES = frozenset(
    {
        "delviery",
        "delivery",
        "delivery number",
        "delivery_number",
        "delivery #",
    }
)


def _normalize_header_key(key: Any) -> str:
    return str(key or "").strip().casefold()


def row_has_header_keys(row: Mapping[str, Any]) -> bool:
    """True when the row dict uses real spreadsheet header names (not positional ``0``…)."""
    for key in row:
        normalized = _normalize_header_key(key)
        if normalized in _DELIVERY_NUMBER_ALIASES:
            return True
    return False


class DeliveryLocationsHeaderMapping(BaseModel):
    """Map logical fields from named spreadsheet columns (case-insensitive)."""

    model_config = ConfigDict(extra="forbid")

    delivery_number: list[str] = Field(default_factory=lambda: list(_DELIVERY_NUMBER_ALIASES))
    name: list[str] = Field(default_factory=lambda: ["Name", "name"])
    street: list[str] = Field(default_factory=lambda: ["Street", "street"])
    street2: list[str] = Field(default_factory=lambda: ["Street 2", "street2", "street 2"])
    zip_code: list[str] = Field(default_factory=lambda: ["Zip Code", "zip", "zip code"])
    city: list[str] = Field(default_factory=lambda: ["City", "city"])
    country: list[str] = Field(
        default_factory=lambda: ["country name", "Country", "country"]
    )

    def _value_for_aliases(self, row: Mapping[str, Any], aliases: list[str]) -> Any:
        alias_set = {_normalize_header_key(a) for a in aliases}
        for key, val in row.items():
            if _normalize_header_key(key) in alias_set:
                return clean_cell_value(val)
        return None

    def materialize_from_headers(self, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            DELIVERY_NUMBER_FIELD: self._value_for_aliases(
                row, self.delivery_number
            ),
            _CANONICAL_NAME: self._value_for_aliases(row, self.name),
            _CANONICAL_STREET: self._value_for_aliases(row, self.street),
            _CANONICAL_STREET2: self._value_for_aliases(row, self.street2),
            _CANONICAL_ZIP: self._value_for_aliases(row, self.zip_code),
            _CANONICAL_CITY: self._value_for_aliases(row, self.city),
            _CANONICAL_COUNTRY: self._value_for_aliases(row, self.country),
        }


DEFAULT_DELIVERY_LOCATIONS_HEADER_MAPPING = DeliveryLocationsHeaderMapping()


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

    def materialize_from_column_letters(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Build canonical keys from Excel column positions (dict value order)."""
        delivery_raw = self._cell(row, self.delivery_number)
        delivery_id = identifier_string_from_cell(delivery_raw)
        if delivery_id is None:
            delivery_id = clean_cell_value(delivery_raw)
        return {
            DELIVERY_NUMBER_FIELD: delivery_id,
            _CANONICAL_NAME: clean_cell_value(self._cell(row, self.name)),
            _CANONICAL_STREET: clean_cell_value(self._cell(row, self.street)),
            _CANONICAL_STREET2: clean_cell_value(self._cell(row, self.street2)),
            _CANONICAL_ZIP: clean_cell_value(self._cell(row, self.zip_code)),
            _CANONICAL_CITY: clean_cell_value(self._cell(row, self.city)),
            _CANONICAL_COUNTRY: clean_cell_value(self._cell(row, self.country)),
        }

    def materialize_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Alias for :meth:`materialize_from_column_letters` (backward compatible)."""
        return self.materialize_from_column_letters(row)


def materialize_delivery_locations_row(
    row: Mapping[str, Any],
    *,
    header_mapping: DeliveryLocationsHeaderMapping | None = None,
    column_mapping: DeliveryLocationsColumnMapping | None = None,
) -> dict[str, Any]:
    """
    Normalize one raw spreadsheet row to canonical Delivery locations keys.

    Order: named headers (when present) → column letters → plain cell cleaning.
    """
    if header_mapping is not None and row_has_header_keys(row):
        return header_mapping.materialize_from_headers(row)
    if column_mapping is not None:
        return column_mapping.materialize_from_column_letters(row)
    return clean_row(dict(row))
