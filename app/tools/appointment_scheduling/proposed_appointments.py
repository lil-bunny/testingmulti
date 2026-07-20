"""Parse scheduling payload date strings for ``shipments.proposed_*`` columns."""

from __future__ import annotations

from datetime import datetime, timezone


def parse_proposed_appointment_date(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None
