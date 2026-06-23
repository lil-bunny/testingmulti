"""Delivery-date cutoff for load-tendering reminder / escalation steps."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.load_tendering_state import get_tender
from app.domain.load_tendering_tender_rows import parse_tender_date
from app.domain.reminder_schedule import DeliveryCutoffSpec
from app.services.workflow_reminder_service import parse_reminders_for_workflow


def _local_time_parts(spec: DeliveryCutoffSpec) -> tuple[int, int]:
    raw = str(spec.local_time or "13:00").strip()
    parts = raw.split(":")
    if len(parts) < 2:
        raise ValueError(f"invalid delivery_cutoff.local_time: {raw!r}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid delivery_cutoff.local_time: {raw!r}")
    return hour, minute


def delivery_reminder_cutoff_at(delivery_date: date, spec: DeliveryCutoffSpec) -> datetime:
    tz = ZoneInfo(str(spec.timezone or "America/Chicago").strip())
    hour, minute = _local_time_parts(spec)
    local_cutoff = datetime.combine(
        delivery_date,
        time(hour=hour, minute=minute),
        tzinfo=tz,
    )
    return local_cutoff.astimezone(timezone.utc)


def past_delivery_reminder_cutoff(
    now_utc: datetime,
    delivery_date: date,
    spec: DeliveryCutoffSpec,
) -> bool:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc >= delivery_reminder_cutoff_at(delivery_date, spec)


def is_past_delivery_cutoff(data: dict[str, Any], *, now_utc: datetime | None = None) -> bool:
    reminders = parse_reminders_for_workflow(data, "load_tendering")
    cutoff_spec = reminders.delivery_cutoff if reminders else None
    if cutoff_spec is None:
        return False
    delivery_date = parse_tender_date((get_tender(data) or {}).get("delivery_date"))
    if delivery_date is None:
        return False
    when = now_utc if now_utc is not None else datetime.now(timezone.utc)
    return past_delivery_reminder_cutoff(when, delivery_date, cutoff_spec)
