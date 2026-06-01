"""Gelita wide-format delivery_location.xlsx column layout."""

from __future__ import annotations

from typing import Final

from app.domain.delivery_locations_column_mapping import DeliveryLocationsColumnMapping

GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS: Final[DeliveryLocationsColumnMapping] = (
    DeliveryLocationsColumnMapping(
        delivery_number="B",
        name="J",
        street="L",
        street2="M",
        zip_code="N",
        city="Q",
        country="BJ",
    )
)
