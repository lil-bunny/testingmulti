"""Tests for Ascend warehouse-availability parsing."""

from __future__ import annotations

from app.domain.appointment_scheduling.scheduling_prompt_templates import format_availability_text
from app.tools.appointment_scheduling.ascend_transforms import (
    _times_from_warehouse_availability,
    normalize_availability_slots,
)

_WAREHOUSE_REF = "9904baba-7c27-4821-a908-fb87f03d7113"


def test_times_from_list_of_docks():
    raw = [
        {
            "dockName": "Dock 36",
            "slots": [
                {"startTime": "17:00:00"},
                {"startTime": "09:00:00"},
                {"startTime": "15:00:00"},
            ],
        },
        {
            "dockName": "Diamond Internal ONLY - Not for Carriers",
            "slots": [{"startTime": "08:00:00"}],
        },
    ]
    assert _times_from_warehouse_availability(raw) == ["09:00", "15:00", "17:00"]


def test_times_from_dict_with_docks_key():
    raw = {
        "docks": [
            {"dockName": "Dock A", "slots": [{"startTime": "10:30:00"}]},
        ]
    }
    assert _times_from_warehouse_availability(raw) == ["10:30"]


def test_times_from_empty_or_none():
    assert _times_from_warehouse_availability(None) == []
    assert _times_from_warehouse_availability([]) == []
    assert _times_from_warehouse_availability({}) == []


def test_normalize_availability_slots_with_list_response():
    def fetch_slots(loc_id_ref: str, iso_date: str, office: str):
        assert loc_id_ref == _WAREHOUSE_REF
        assert office == "DIAMOND-RPN"
        if iso_date != "2026-08-03":
            return []
        return [{"dockName": "Dock 36", "slots": [{"startTime": "15:00:00"}]}]

    result = normalize_availability_slots(
        [{"warehouse": _WAREHOUSE_REF}],
        "08/03/2026",
        "DIAMOND-RPN",
        fetch_slots=fetch_slots,
    )

    assert result["total_dates"] == 1
    assert result["location_ref"] == _WAREHOUSE_REF
    assert result["availability"]["08/03/2026"]["times"] == ["15:00"]


def test_format_availability_text_from_normalized_result():
    def fetch_slots(_loc: str, iso_date: str, _office: str):
        if iso_date != "2026-08-03":
            return []
        return [{"dockName": "Dock 36", "slots": [{"startTime": "09:00:00"}]}]

    normalized = normalize_availability_slots(
        [{"warehouse": _WAREHOUSE_REF}],
        "08/03/2026",
        "DIAMOND-RPN",
        fetch_slots=fetch_slots,
    )
    text = format_availability_text(normalized)

    assert text != "(no availability slots)"
    assert "09:00" in text
