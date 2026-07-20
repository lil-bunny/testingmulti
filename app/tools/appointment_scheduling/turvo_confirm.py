"""Pure Turvo confirm-phase delivery placeholder helpers (0001 rule)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class TurvoDeliveryPlaceholder:
    stop_name: str
    start_time: str


def normalize_date_only(raw_value: Any) -> str | None:
    if not raw_value:
        return None
    value = str(raw_value).strip()
    if not value:
        return None
    if "T" in value:
        value = value.split("T", 1)[0]
    elif " " in value and "-" in value:
        value = value.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if len(value) >= 10 and value[4] == "-" and value[7] == "-":
        return value[:10]
    return None


def prepare_delivery_placeholder(
    *,
    stop_name: str,
    delivery_date: str,
) -> TurvoDeliveryPlaceholder | None:
    """Return delivery stop wall time ``YYYY-MM-DD 00:01:00`` (0001 rule)."""
    name = str(stop_name or "").strip()
    normalized_date = normalize_date_only(delivery_date)
    if not name or not normalized_date:
        return None
    return TurvoDeliveryPlaceholder(
        stop_name=name,
        start_time=f"{normalized_date} 00:01:00",
    )
