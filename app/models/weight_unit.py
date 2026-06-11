"""Domain enum for tender product order-quantity unit (Ship Schedule ME)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

_KG_ALIASES = frozenset({"kg", "kgm", "kilogram", "kilograms"})
_LB_ALIASES = frozenset({"lbs", "pound", "pounds"})

class WeightUnit(StrEnum):
    """Row ``weight_unit`` for ``tender_products`` (PostgreSQL enum)."""

    KG = "kg"
    LBS = "lbs"

    @classmethod
    def parse(cls, val: Any) -> WeightUnit | None:
        """Normalize Ship Schedule ``ME`` cell or DB text to enum member."""
        if val is None:
            return None
        if isinstance(val, WeightUnit):
            return val
        text = str(val).strip().casefold()
        if not text:
            return None
        if text in _KG_ALIASES:
            return cls.KG
        if text in _LB_ALIASES:
            return cls.LBS
        return None
