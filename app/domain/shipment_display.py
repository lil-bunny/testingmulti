"""Display fields for ``shipments`` rows sourced from Turvo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ShipmentDisplayFields:
    carrier_name: str | None = None
    customer_name: str | None = None
    pickup_date: datetime | None = None
    pickup_timezone: str | None = None
    delivery_date: datetime | None = None
    delivery_timezone: str | None = None
