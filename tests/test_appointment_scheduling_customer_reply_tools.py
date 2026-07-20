"""Tests for appointment scheduling customer reply pure tools."""

from __future__ import annotations

from app.tools.appointment_scheduling.customer_reply import (
    INSUFFICIENT,
    SUFFICIENT,
    build_ascend_dropoff_update_payload,
    build_customer_reply_result,
    format_appointment_start_iso,
    format_turvo_stop_start_time,
)


def test_format_appointment_start_iso_am_pm() -> None:
    assert format_appointment_start_iso("07/18/2026", "10:30 AM") == "2026-07-18T10:30:00"
    assert format_turvo_stop_start_time("07/18/2026", "10:30 AM") == "2026-07-18 10:30:00"


def test_build_customer_reply_result_sufficient() -> None:
    parsed = build_customer_reply_result(
        {
            "success": True,
            "extracted_date": "2026-07-18",
            "extracted_time": "14:00",
            "confidence": 0.9,
            "reason": "confirmed",
        }
    )
    assert parsed["decision"] == SUFFICIENT
    assert parsed["appointment_start_iso"] == "2026-07-18T14:00:00"


def test_build_customer_reply_result_missing_time_is_insufficient() -> None:
    parsed = build_customer_reply_result(
        {
            "success": True,
            "extracted_date": "2026-07-18",
            "extracted_time": None,
            "confidence": 0.5,
            "reason": "date only",
        }
    )
    assert parsed["decision"] == INSUFFICIENT


def test_build_ascend_dropoff_update_payload() -> None:
    payload = build_ascend_dropoff_update_payload(
        {"stop_id": 99, "stop_number": 2},
        "2026-07-18T10:30:00",
    )
    assert payload["shipmentStops"][0]["id"] == 99
    assert payload["shipmentStops"][0]["appointmentStart"] == "2026-07-18T10:30:00"
