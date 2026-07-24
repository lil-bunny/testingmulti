"""Pure date/time helpers for appointment scheduling."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_weekend_shifted_truthy(value: Any) -> bool:
    """Coerce LLM/UI weekend_shifted values to bool."""
    if value is True:
        return True
    if value is None:
        return False
    try:
        normalized = str(value).strip().lower()
    except Exception:
        return False
    return normalized in ("true", "1", "yes", "y", "on")


def _parse_date_only(text: str) -> datetime | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _parse_wall_time(text: str) -> tuple[int, int] | None:
    cleaned = str(text or "").strip()
    if not cleaned:
        return None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.hour, parsed.minute
        except ValueError:
            continue
    return None


def proposed_wall_clock_to_utc(
    date_raw: str | None,
    *,
    time_raw: str | None = None,
    timezone_name: str | None = None,
) -> datetime | None:
    """Interpret date (+ optional wall time) in stop timezone; return UTC."""
    text = str(date_raw or "").strip()
    if not text:
        return None
    date_part = _parse_date_only(text)
    if date_part is None:
        return None

    hour, minute = 0, 0
    if time_raw:
        parsed_time = _parse_wall_time(time_raw)
        if parsed_time is None:
            return None
        hour, minute = parsed_time

    tz_str = str(timezone_name or "").strip()
    if tz_str:
        try:
            local_dt = date_part.replace(
                hour=hour,
                minute=minute,
                second=0,
                microsecond=0,
                tzinfo=ZoneInfo(tz_str),
            )
            return local_dt.astimezone(timezone.utc)
        except ZoneInfoNotFoundError:
            pass

    return date_part.replace(hour=hour, minute=minute, tzinfo=timezone.utc)


def parse_proposed_appointment_date(raw: str | None) -> datetime | None:
    return proposed_wall_clock_to_utc(raw)


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
