"""Unit tests for the pure deterministic scheduling fallback."""

from __future__ import annotations

from app.tools.appointment_scheduling.scheduling_fallback import (
    compute_delivery_calendar,
    fallback_scheduling_decision,
    transit_days_for,
)


def test_transit_days_distance_bands_take_priority() -> None:
    # 900-1200 band wins over the OR state rule.
    assert transit_days_for(1000, "OR") == 2
    assert transit_days_for(1500, "CO") == 3
    assert transit_days_for(2000, "OR") == 4
    assert transit_days_for(2500, "OR") == 5


def test_transit_days_state_fallback() -> None:
    assert transit_days_for(300, "OR") == 2
    assert transit_days_for(100, "NV") == 1
    assert transit_days_for(50, "Nevada") == 1
    assert transit_days_for(400, "Georgia") == 4


def test_transit_days_general_distance_fallback() -> None:
    assert transit_days_for(400, "ZZ") == 1
    assert transit_days_for(700, "ZZ") == 2


def test_compute_delivery_calendar_add_crosses_weekend_no_shift() -> None:
    # Friday + 3 calendar days = Monday (weekday), so no weekend shift.
    delivery, weekday, shifted = compute_delivery_calendar("07/03/2026", 3)
    assert delivery == "07/06/2026"
    assert weekday == "MONDAY"
    assert shifted is False


def test_compute_delivery_calendar_shifts_off_weekend() -> None:
    # Wednesday + 3 = Saturday -> shift forward to Monday.
    delivery, weekday, shifted = compute_delivery_calendar("07/08/2026", 3)
    assert delivery == "07/13/2026"
    assert weekday == "MONDAY"
    assert shifted is True


def test_compute_delivery_calendar_bad_input_returns_unchanged() -> None:
    delivery, weekday, shifted = compute_delivery_calendar("not-a-date", 3)
    assert delivery == "not-a-date"
    assert weekday == "DAY"
    assert shifted is False


def test_fallback_scheduling_decision_end_to_end() -> None:
    decision = fallback_scheduling_decision(
        pickup_mm_dd_yyyy="07/08/2026", miles=300, dropoff_state="OR"
    )
    assert decision.transit_days == 2
    assert decision.calculated_delivery_date == "07/10/2026"
    assert decision.calculated_delivery_weekday == "FRIDAY"
    assert decision.selected_pickup_date == "07/08/2026"
    assert decision.weekend_shifted is False
