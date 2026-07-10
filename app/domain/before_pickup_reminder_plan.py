"""Pure planner for ``before_pickup`` reminder scheduling (catch-up + min gap)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.domain.reminder_schedule import ReminderStepSpec


@dataclass
class BeforePickupReminderPlan:
    hours_remaining: float
    catch_up: ReminderStepSpec | None = None
    scheduled: list[tuple[ReminderStepSpec, datetime]] = field(default_factory=list)
    suppressed: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


def _step_num(step: ReminderStepSpec, index: int) -> int:
    return step.step if step.step is not None else index


def _step_info(step: ReminderStepSpec, index: int, fire_at: datetime) -> dict[str, Any]:
    return {
        "step": _step_num(step, index),
        "delay_hours": float(step.delay_hours),
        "fire_at": fire_at.isoformat(),
    }


def _same_step(a: ReminderStepSpec, b: ReminderStepSpec) -> bool:
    return float(a.delay_hours) == float(b.delay_hours) and a.event_type == b.event_type


def _select_catch_up_step(
    steps: list[ReminderStepSpec],
    hours_remaining: float,
) -> ReminderStepSpec | None:
    """Upper threshold of the band ``lower < R <= upper`` (pickup-anchored offsets)."""
    offsets = sorted({float(s.delay_hours) for s in steps}, reverse=True)
    if not offsets or hours_remaining > offsets[0]:
        return None

    for index, upper in enumerate(offsets):
        lower = offsets[index + 1] if index + 1 < len(offsets) else 0.0
        if lower < hours_remaining <= upper:
            for step in steps:
                if float(step.delay_hours) == upper:
                    return step
    return None


def _legacy_plan(
    *,
    pickup_at: datetime,
    now: datetime,
    steps: list[ReminderStepSpec],
    hours_remaining: float,
) -> BeforePickupReminderPlan:
    scheduled: list[tuple[ReminderStepSpec, datetime]] = []
    skipped: list[dict[str, Any]] = []
    for index, step in enumerate(steps, start=1):
        fire_at = pickup_at - timedelta(hours=float(step.delay_hours))
        info = _step_info(step, index, fire_at)
        if fire_at <= now:
            skipped.append(info)
        else:
            scheduled.append((step, fire_at))
    return BeforePickupReminderPlan(
        hours_remaining=hours_remaining,
        scheduled=scheduled,
        skipped=skipped,
    )


def plan_before_pickup_reminders(
    *,
    pickup_at: datetime,
    now: datetime,
    steps: list[ReminderStepSpec],
    min_gap_hours: float = 3.0,
    catch_up_enabled: bool = True,
) -> BeforePickupReminderPlan:
    """Plan catch-up (optional), pickup-anchored ETAs, and gap suppressions."""
    hours_remaining = (pickup_at - now).total_seconds() / 3600.0

    if not catch_up_enabled:
        return _legacy_plan(
            pickup_at=pickup_at,
            now=now,
            steps=steps,
            hours_remaining=hours_remaining,
        )

    catch_up: ReminderStepSpec | None = None
    if catch_up_enabled:
        catch_up = _select_catch_up_step(steps, hours_remaining)

    skipped: list[dict[str, Any]] = []
    candidates: list[tuple[ReminderStepSpec, datetime, int]] = []

    for index, step in enumerate(steps, start=1):
        fire_at = pickup_at - timedelta(hours=float(step.delay_hours))
        info = _step_info(step, index, fire_at)
        if catch_up is not None and _same_step(step, catch_up):
            continue
        if fire_at <= now:
            skipped.append(info)
        else:
            candidates.append((step, fire_at, index))

    candidates.sort(key=lambda item: item[1])

    last_send_at: datetime | None = now if catch_up is not None else None
    scheduled: list[tuple[ReminderStepSpec, datetime]] = []
    suppressed: list[dict[str, Any]] = []

    for step, fire_at, index in candidates:
        if last_send_at is not None:
            gap_hours = (fire_at - last_send_at).total_seconds() / 3600.0
            if gap_hours < min_gap_hours:
                info = _step_info(step, index, fire_at)
                info["reason"] = "gap_lt_min"
                suppressed.append(info)
                continue
        scheduled.append((step, fire_at))
        last_send_at = fire_at

    return BeforePickupReminderPlan(
        hours_remaining=hours_remaining,
        catch_up=catch_up,
        scheduled=scheduled,
        suppressed=suppressed,
        skipped=skipped,
    )
