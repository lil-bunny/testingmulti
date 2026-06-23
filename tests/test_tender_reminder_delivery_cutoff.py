"""Tests for delivery-date reminder cutoff helpers."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from app.domain.load_tendering_tender_rows import parse_tender_date
from app.domain.reminder_schedule import DeliveryCutoffSpec
from app.tools.tender_reminder_delivery_cutoff import (
    delivery_reminder_cutoff_at,
    is_past_delivery_cutoff,
    past_delivery_reminder_cutoff,
)


def test_parse_tender_date_iso_z_uses_calendar_date() -> None:
    assert parse_tender_date("2026-06-11T18:30:00.000Z") == date(2026, 6, 11)


def test_cutoff_winter_chicago_to_utc() -> None:
    spec = DeliveryCutoffSpec(local_time="13:00", timezone="America/Chicago")
    cutoff = delivery_reminder_cutoff_at(date(2026, 1, 15), spec)
    assert cutoff == datetime(2026, 1, 15, 19, 0, tzinfo=timezone.utc)


def test_cutoff_summer_chicago_to_utc() -> None:
    spec = DeliveryCutoffSpec(local_time="13:00", timezone="America/Chicago")
    cutoff = delivery_reminder_cutoff_at(date(2026, 6, 20), spec)
    assert cutoff == datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc)


def test_past_cutoff_before_send_window() -> None:
    spec = DeliveryCutoffSpec()
    now = datetime(2026, 6, 20, 17, 59, tzinfo=timezone.utc)
    assert past_delivery_reminder_cutoff(now, date(2026, 6, 20), spec) is False


def test_past_cutoff_at_and_after_cutoff() -> None:
    spec = DeliveryCutoffSpec()
    delivery = date(2026, 6, 20)
    assert past_delivery_reminder_cutoff(
        datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc), delivery, spec
    )
    assert past_delivery_reminder_cutoff(
        datetime(2026, 6, 21, 0, 0, tzinfo=timezone.utc), delivery, spec
    )


def test_is_past_delivery_cutoff_from_state() -> None:
    data = {
        "tenant_settings": {
            "load_tendering": {
                "reminders": {
                    "steps": [{"delay_hours": 1, "event_type": "reminder_due"}],
                    "delivery_cutoff": {"local_time": "13:00", "timezone": "America/Chicago"},
                }
            }
        },
        "tender": {"delivery_date": "2026-06-20"},
    }
    before = datetime(2026, 6, 20, 17, 59, tzinfo=timezone.utc)
    after = datetime(2026, 6, 20, 18, 0, tzinfo=timezone.utc)
    assert is_past_delivery_cutoff(data, now_utc=before) is False
    assert is_past_delivery_cutoff(data, now_utc=after) is True


def test_invalid_local_time_raises() -> None:
    spec = DeliveryCutoffSpec(local_time="bad", timezone="America/Chicago")
    with pytest.raises(ValueError):
        delivery_reminder_cutoff_at(date(2026, 6, 20), spec)
