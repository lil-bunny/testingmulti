"""Display fields for ``shipments`` rows sourced from Turvo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ShipmentDisplayFields:
    carrier_name: str | None = None
    customer_name: str | None = None
    delivery_date: date | None = None
