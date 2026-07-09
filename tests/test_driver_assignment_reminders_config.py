"""Unit tests for driver_assignment reminders config."""

from __future__ import annotations

from app.domain.driver_assignment.reminders_config import (
    DriverAssignmentRemindersConfig,
    parse_driver_assignment_reminders,
)


def test_legacy_offsets_normalize_to_steps() -> None:
    cfg = DriverAssignmentRemindersConfig.model_validate(
        {"offsets_before_pickup_hours": [48, 24, 12, 6]}
    )
    assert [s.delay_hours for s in cfg.steps] == [48, 24, 12, 6]
    assert all(s.event_type == "reminder_due" for s in cfg.steps)


def test_legacy_algorithm_keys_ignored_but_min_gap_kept() -> None:
    cfg = DriverAssignmentRemindersConfig.model_validate(
        {
            "steps": [{"step": 1, "event_type": "reminder_due", "delay_hours": 48}],
            "schedule_mode": "before_pickup",
            "catch_up_missed_steps": False,
            "min_gap_hours": 4,
            "expire_grace_hours": 99,
        }
    )
    dumped = cfg.model_dump()
    assert "schedule_mode" not in dumped
    assert "catch_up_missed_steps" not in dumped
    assert "expire_grace_hours" not in dumped
    assert cfg.min_gap_hours == 4


def test_min_gap_hours_defaults_to_three() -> None:
    cfg = DriverAssignmentRemindersConfig.model_validate(
        {"steps": [{"step": 1, "event_type": "reminder_due", "delay_hours": 48}]}
    )
    assert cfg.min_gap_hours == 3.0


def test_parse_driver_assignment_reminders_from_tenant_settings() -> None:
    tenant_settings = {
        "driver_assignment": {
            "reminders": {
                "steps": [
                    {"step": 1, "event_type": "reminder_due", "delay_hours": 24},
                ],
                "email_template_html": "<html/>",
            }
        }
    }
    cfg = parse_driver_assignment_reminders(tenant_settings)
    assert cfg is not None
    assert cfg.steps[0].delay_hours == 24
    assert cfg.resolve_email_body() == "<html/>"


def test_parse_driver_assignment_reminders_missing_block() -> None:
    assert parse_driver_assignment_reminders({}) is None
    assert parse_driver_assignment_reminders({"driver_assignment": {}}) is None
