"""Unit tests for before_pickup reminder planning."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.before_pickup_reminder_plan import plan_before_pickup_reminders
from app.domain.reminder_schedule import ReminderStepSpec


def _t3ra_steps() -> list[ReminderStepSpec]:
    return [
        ReminderStepSpec(step=1, event_type="reminder_due", delay_hours=48),
        ReminderStepSpec(step=2, event_type="reminder_due", delay_hours=24),
        ReminderStepSpec(step=3, event_type="reminder_due", delay_hours=12),
        ReminderStepSpec(step=4, event_type="reminder_due", delay_hours=6),
        ReminderStepSpec(step=5, event_type="escalation_due", delay_hours=3),
    ]


def _plan_at_r(hours_remaining: float, **kwargs):
    pickup_at = datetime(2026, 7, 8, 17, 0, tzinfo=timezone.utc)
    now = pickup_at - timedelta(hours=hours_remaining)
    return plan_before_pickup_reminders(
        pickup_at=pickup_at,
        now=now,
        steps=_t3ra_steps(),
        **kwargs,
    )


def _delay_hours(steps: list[ReminderStepSpec]) -> list[float]:
    return [float(s.delay_hours) for s in steps]


def test_r50_no_catch_up_all_scheduled() -> None:
    plan = _plan_at_r(50)
    assert plan.catch_up is None
    assert _delay_hours([s for s, _ in plan.scheduled]) == [48, 24, 12, 6, 3]
    assert plan.suppressed == []
    assert plan.skipped == []


def test_r30_catch_up_48_schedules_rest() -> None:
    plan = _plan_at_r(30)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 48
    assert _delay_hours([s for s, _ in plan.scheduled]) == [24, 12, 6, 3]
    assert plan.suppressed == []


def test_r27_catch_up_48_and_24_scheduled() -> None:
    plan = _plan_at_r(27)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 48
    assert _delay_hours([s for s, _ in plan.scheduled]) == [24, 12, 6, 3]
    assert plan.suppressed == []


def test_r25_catch_up_48_suppresses_24() -> None:
    plan = _plan_at_r(25)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 48
    assert _delay_hours([s for s, _ in plan.scheduled]) == [12, 6, 3]
    assert len(plan.suppressed) == 1
    assert plan.suppressed[0]["delay_hours"] == 24
    assert plan.suppressed[0]["reason"] == "gap_lt_min"


def test_r20_catch_up_24() -> None:
    plan = _plan_at_r(20)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 24
    assert _delay_hours([s for s, _ in plan.scheduled]) == [12, 6, 3]
    assert plan.suppressed == []


def test_r10_catch_up_12() -> None:
    plan = _plan_at_r(10)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 12
    assert _delay_hours([s for s, _ in plan.scheduled]) == [6, 3]
    assert plan.suppressed == []


def test_gap_boundary_299h_suppresses_24() -> None:
    plan = _plan_at_r(26.99)
    assert plan.catch_up is not None
    assert float(plan.catch_up.delay_hours) == 48
    assert _delay_hours([s for s, _ in plan.scheduled]) == [12, 6, 3]
    assert len(plan.suppressed) == 1
    assert plan.suppressed[0]["delay_hours"] == 24


def test_legacy_mode_matches_skip_only() -> None:
    plan = _plan_at_r(10, catch_up_enabled=False)
    assert plan.catch_up is None
    assert _delay_hours([s for s, _ in plan.scheduled]) == [6, 3]
    assert len(plan.skipped) == 3
    assert {s["delay_hours"] for s in plan.skipped} == {48, 24, 12}


@pytest.mark.parametrize(
    ("hours_remaining", "expected_scheduled"),
    [
        (120, [48, 24, 12, 6]),
        (10, [6]),
    ],
)
def test_legacy_four_step_offsets(hours_remaining: float, expected_scheduled: list[float]) -> None:
    pickup_at = datetime(2026, 7, 8, 17, 0, tzinfo=timezone.utc)
    now = pickup_at - timedelta(hours=hours_remaining)
    steps = [
        ReminderStepSpec(step=1, delay_hours=48),
        ReminderStepSpec(step=2, delay_hours=24),
        ReminderStepSpec(step=3, delay_hours=12),
        ReminderStepSpec(step=4, delay_hours=6),
    ]
    plan = plan_before_pickup_reminders(
        pickup_at=pickup_at,
        now=now,
        steps=steps,
        catch_up_enabled=False,
    )
    assert _delay_hours([s for s, _ in plan.scheduled]) == expected_scheduled
