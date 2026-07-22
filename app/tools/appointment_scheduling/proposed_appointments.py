"""Parse scheduling payload date strings for ``shipments.proposed_*`` columns."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
