"""Tests for Turvo confirm placeholder pure tool."""

from __future__ import annotations

from app.tools.appointment_scheduling.turvo_confirm import (
    normalize_date_only,
    prepare_delivery_placeholder,
)


def test_normalize_date_only_iso() -> None:
    assert normalize_date_only("2026-07-18T10:30:00Z") == "2026-07-18"


def test_prepare_delivery_placeholder_0001() -> None:
    placeholder = prepare_delivery_placeholder(
        stop_name="Costco Depot",
        delivery_date="2026-07-18",
    )
    assert placeholder is not None
    assert placeholder.stop_name == "Costco Depot"
    assert placeholder.start_time == "2026-07-18 00:01:00"


def test_prepare_delivery_placeholder_missing_fields() -> None:
    assert prepare_delivery_placeholder(stop_name="", delivery_date="2026-07-18") is None
