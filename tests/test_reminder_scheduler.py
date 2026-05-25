"""Unit tests for reminder payload helpers (workflow reminder service)."""

from app.services.workflow_reminder_service import _reminder_offset_label


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
