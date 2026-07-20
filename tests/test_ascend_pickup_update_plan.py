"""Tests for plan_ascend_pickup_update pure tool."""

from __future__ import annotations

from app.tools.appointment_scheduling.ascend_pickup_update import plan_ascend_pickup_update


def _appointment(*, start: str, end: str = "2026-07-01T12:00:00") -> dict:
    return {
        "appointmentId": "appt-1",
        "stopNumber": 1,
        "requestType": "LIVE_LOAD",
        "startTime": start,
        "endTime": end,
    }


def test_plan_skips_when_date_time_unchanged() -> None:
    appointments = [_appointment(start="2026-07-01T08:00:00")]
    plan = plan_ascend_pickup_update(appointments, "2026-07-01", "08:00")
    assert plan.should_apply is False


def test_plan_applies_when_pickup_changed() -> None:
    appointments = [_appointment(start="2026-06-28T08:00:00")]
    plan = plan_ascend_pickup_update(appointments, "2026-07-01", "08:00")
    assert plan.should_apply is True
    assert plan.appointment_id == "appt-1"
    assert plan.update_body is not None
    assert plan.update_body["startTime"] == "2026-07-01T08:00:00"
    assert plan.turvo_pickup_start_time == "2026-07-01 08:00:00"


def test_plan_empty_appointments() -> None:
    plan = plan_ascend_pickup_update([], "2026-07-01", "08:00")
    assert plan.should_apply is False
