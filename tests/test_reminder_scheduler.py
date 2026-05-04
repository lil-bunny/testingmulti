"""Unit tests for POD reminder scheduling labels (sub-hour .env support)."""

from app.services.reminder_scheduler import (
    _build_reminder_payload,
    _reminder_offset_label,
)


def test_reminder_offset_label_seconds() -> None:
    assert _reminder_offset_label(30 / 3600) == "30s"
    assert _reminder_offset_label(0.00833333) == "30s"


def test_reminder_offset_label_minutes() -> None:
    assert _reminder_offset_label(5 / 60) == "5m"


def test_reminder_offset_label_whole_hours() -> None:
    assert _reminder_offset_label(0) == "0h"
    assert _reminder_offset_label(-2) == "0h"
    assert _reminder_offset_label(1.0) == "1h"
    assert _reminder_offset_label(24.0) == "24h"


def test_reminder_offset_label_fractional_hours() -> None:
    assert _reminder_offset_label(1.5) == "1.5h"


def test_build_reminder_payload_subjects() -> None:
    base = {
        "tenant_id": "t1",
        "workflow_instance_id": "w1",
        "subject": "Load 123 POD",
    }
    p0 = _build_reminder_payload(base, 0.00833333, 0)
    assert p0["subject"] == "Load 123 POD"

    p1 = _build_reminder_payload(base, 5 / 60, 1)
    assert p1["subject"] == "POD Reminder (5m)"

    p1s = _build_reminder_payload(base, 30 / 3600, 1)
    assert p1s["subject"] == "POD Reminder (30s)"
