"""Pure metadata hydration helpers for appointment scheduling."""

from __future__ import annotations

from app.domain.appointment_scheduling.metadata_hydration import (
    rebuild_llm_appointment_decision_from_shipment_row,
)
from app.tools.appointment_scheduling.dates import (
    proposed_wall_clock_to_utc,
    utc_to_local_date_and_time,
)


def test_utc_to_local_date_and_time_round_trips_proposed_wall_clock():
    utc_dt = proposed_wall_clock_to_utc(
        "2026-07-01",
        time_raw="08:00",
        timezone_name="America/Chicago",
    )
    assert utc_dt is not None

    pickup_date, pickup_time = utc_to_local_date_and_time(
        utc_dt,
        timezone_name="America/Chicago",
    )
    assert pickup_date == "2026-07-01"
    assert pickup_time == "08:00"


def test_rebuild_llm_appointment_decision_from_shipment_row():
    proposed_pickup = proposed_wall_clock_to_utc(
        "2026-07-01",
        time_raw="08:00",
        timezone_name="America/Chicago",
    )
    proposed_delivery = proposed_wall_clock_to_utc(
        "07/04/2026",
        timezone_name="America/Los_Angeles",
    )
    assert proposed_pickup is not None
    assert proposed_delivery is not None

    decision = rebuild_llm_appointment_decision_from_shipment_row(
        {
            "proposed_pickup": proposed_pickup,
            "proposed_delivery": proposed_delivery,
            "pickup_timezone": "America/Chicago",
            "delivery_timezone": "America/Los_Angeles",
        }
    )

    assert "weekend_shifted" not in decision
    assert decision["selected_pickup_date"] == "2026-07-01"
    assert decision["selected_pickup_time"] == "08:00"
    assert decision["calculated_delivery_date"] == "07/04/2026"
    assert decision["calculated_delivery_weekday"] == "SATURDAY"


def test_rebuild_returns_empty_without_durable_facts():
    assert rebuild_llm_appointment_decision_from_shipment_row({}) == {}
    assert rebuild_llm_appointment_decision_from_shipment_row(
        {"metadata": {"weekend_shifted": False}}
    ) == {}


def test_rebuild_accepts_iso_string_timestamps():
    decision = rebuild_llm_appointment_decision_from_shipment_row(
        {
            "proposed_pickup": "2026-07-01T13:00:00+00:00",
            "pickup_timezone": "America/Chicago",
        }
    )
    assert "weekend_shifted" not in decision
    assert decision["selected_pickup_date"] == "2026-07-01"
    assert decision["selected_pickup_time"] == "08:00"
