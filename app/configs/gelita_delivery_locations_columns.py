"""Wide positional column layout for headerless delivery_location.xlsx (Gelita tenant).

Business layout (unchanged):
- C: delivery address code (join key to Ship Schedule column E / LIEFAN)
- E: delivery address name
- J: customer name (tenders.customer_name via LIEFAN lookup)
- L: street address
- N: zip code
- Q: city
"""

from __future__ import annotations

from typing import Final

from app.domain.delivery_locations_column_mapping import DeliveryLocationsColumnMapping

GELITA_WIDE_DELIVERY_LOCATIONS_COLUMNS: Final[DeliveryLocationsColumnMapping] = (
    DeliveryLocationsColumnMapping(
        delivery_number="C",
        name="E",
        customer_name="J",
        street="L",
        street2="M",
        zip_code="N",
        city="Q",
        country="BJ",
    )
)
