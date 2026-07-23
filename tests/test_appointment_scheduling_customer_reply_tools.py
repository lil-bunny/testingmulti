"""Tests for appointment scheduling customer reply pure tools."""

from __future__ import annotations

from app.tools.appointment_scheduling.customer_reply import (
    ACCEPTED,
    DO_NOTHING,
    REJECTED,
    build_ascend_dropoff_update_payload,
    build_customer_reply_result,
    format_appointment_start_iso,
    format_turvo_stop_start_time,
    normalize_customer_reply_decision,
)


def test_format_appointment_start_iso_am_pm() -> None:
    assert format_appointment_start_iso("07/18/2026", "10:30 AM") == "2026-07-18T10:30:00"
    assert format_turvo_stop_start_time("07/18/2026", "10:30 AM") == "2026-07-18 10:30:00"


def test_build_customer_reply_result_accepted() -> None:
    parsed = build_customer_reply_result(
        {
            "decision": ACCEPTED,
            "success": True,
            "extracted_date": "2026-07-18",
            "extracted_time": "14:00",
            "confidence": 0.9,
            "reason": "confirmed",
        }
    )
    assert parsed["decision"] == ACCEPTED
    assert parsed["appointment_start_iso"] == "2026-07-18T14:00:00"


def test_build_customer_reply_result_accepted_missing_time_is_rejected() -> None:
    parsed = build_customer_reply_result(
        {
            "decision": ACCEPTED,
            "success": True,
            "extracted_date": "2026-07-18",
            "extracted_time": None,
            "confidence": 0.5,
            "reason": "date only",
        }
    )
    assert parsed["decision"] == REJECTED


def test_normalize_unknown_decision_defaults_to_do_nothing() -> None:
    assert normalize_customer_reply_decision({"decision": "sufficient"}) == DO_NOTHING
    assert normalize_customer_reply_decision({"decision": "garbage"}) == DO_NOTHING


def test_build_ascend_dropoff_update_payload() -> None:
    payload = build_ascend_dropoff_update_payload(
        {"stop_id": 99, "stop_number": 2},
        "2026-07-18T10:30:00",
    )
    assert payload["shipmentStops"][0]["id"] == 99
    assert payload["shipmentStops"][0]["appointmentStart"] == "2026-07-18T10:30:00"
