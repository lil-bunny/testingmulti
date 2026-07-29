"""Pure helpers for appointment scheduling customer-reply LLM output (no I/O)."""

from __future__ import annotations

import re
from typing import Any

from app.domain.appointment_scheduling.utils import clean_optional_str

ACCEPTED = "accepted"
REJECTED = "rejected"
DO_NOTHING = "do_nothing"

_CUSTOMER_REPLY_DECISIONS = frozenset({ACCEPTED, REJECTED, DO_NOTHING})


def normalize_customer_reply_decision(raw: dict[str, Any]) -> str:
    decision = str(raw.get("decision") or "").strip().lower()
    if decision in _CUSTOMER_REPLY_DECISIONS:
        return decision
    success = raw.get("success")
    if success is True:
        return ACCEPTED
    if success is False:
        return DO_NOTHING
    return DO_NOTHING


def _parse_date_parts(date_str: str | None) -> tuple[str, str, str] | None:
    if not date_str:
        return None
    cleaned = str(date_str).strip().replace("/", "-")
    parts = cleaned.split("-")
    if len(parts) == 3 and parts[0].isdigit() and len(parts[0]) == 4:
        year, month, day = parts
        return year, month.zfill(2), day.zfill(2)
    if len(parts) != 3:
        return None
    first, second, yr = parts
    if not yr.isdigit() or len(yr) != 4:
        return None
    try:
        first_num = int(first)
        second_num = int(second)
    except ValueError:
        return None
    is_day_first = first_num > 12
    month = str(second_num if is_day_first else first_num).zfill(2)
    day = str(first_num if is_day_first else second_num).zfill(2)
    return yr, month, day


def _parse_time_parts(time_str: str | None) -> tuple[int, str] | None:
    if not time_str:
        return None
    time_clean = str(time_str).strip()
    match = re.match(r"^(\d{1,2}):(\d{2})\s*(AM|PM)?$", time_clean, re.IGNORECASE)
    if match:
        hours = int(match.group(1))
        minutes = match.group(2)
        ampm = match.group(3)
        if ampm:
            ampm = ampm.upper()
            if ampm == "PM" and hours < 12:
                hours += 12
            if ampm == "AM" and hours == 12:
                hours = 0
        return hours, minutes
    parts = time_clean.split(":")
    if len(parts) < 2:
        return None
    h_raw = "".join(ch for ch in parts[0] if ch.isdigit())
    m_raw = "".join(ch for ch in parts[1] if ch.isdigit())
    if not h_raw or not m_raw:
        return None
    return int(h_raw), m_raw


def format_appointment_start_iso(date_str: str | None, time_str: str | None) -> str | None:
    """ISO local datetime for Ascend ``appointmentStart`` (no timezone suffix)."""
    date_parts = _parse_date_parts(date_str)
    time_parts = _parse_time_parts(time_str)
    if not date_parts or not time_parts:
        return None
    year, month, day = date_parts
    hours, minutes = time_parts
    return f"{year}-{month}-{day}T{str(hours).zfill(2)}:{minutes}:00"


def format_turvo_stop_start_time(date_str: str | None, time_str: str | None) -> str | None:
    """Turvo wall time ``YYYY-MM-DD HH:MM:SS``."""
    date_parts = _parse_date_parts(date_str)
    time_parts = _parse_time_parts(time_str)
    if not date_parts or not time_parts:
        return None
    year, month, day = date_parts
    hours, minutes = time_parts
    return f"{year}-{month}-{day} {str(hours).zfill(2)}:{minutes}:00"


def extract_dropoff_stop(ascend_shipment: dict[str, Any]) -> dict[str, Any]:
    """Last stop from Ascend ``shipmentStops``."""
    if not isinstance(ascend_shipment, dict):
        return {}
    stops = ascend_shipment.get("shipmentStops") or []
    if not isinstance(stops, list) or not stops:
        return {}
    dropoff = stops[-1] if isinstance(stops[-1], dict) else {}
    return {
        "stop_id": dropoff.get("id"),
        "stop_number": dropoff.get("stopNumber"),
        "stop_name": dropoff.get("stopName") or dropoff.get("warehouseName"),
    }


def build_ascend_dropoff_update_payload(
    dropoff_stop: dict[str, Any],
    iso_start: str,
) -> dict[str, Any]:
    stop_id = dropoff_stop.get("stop_id")
    if stop_id is None or not iso_start:
        return {}
    return {
        "shipmentStops": [
            {
                "id": stop_id,
                "stopNumber": dropoff_stop.get("stop_number") or "",
                "appointmentStart": iso_start,
            }
        ]
    }


def build_customer_reply_result(raw: dict[str, Any]) -> dict[str, Any]:
    """Map LLM JSON to normalized decision and extracted date/time fields."""
    extracted_date = clean_optional_str(raw.get("extracted_date"))
    extracted_time = clean_optional_str(raw.get("extracted_time"))
    decision = normalize_customer_reply_decision(raw)
    if decision == ACCEPTED and not (
        extracted_date and extracted_time and format_appointment_start_iso(extracted_date, extracted_time)
    ):
        decision = REJECTED
    try:
        confidence = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    reason = str(raw.get("reason") or "").strip() or "no reason"
    return {
        "decision": decision,
        "confidence": confidence,
        "reason": reason,
        "extracted_date": extracted_date,
        "extracted_time": extracted_time,
        "appointment_start_iso": format_appointment_start_iso(extracted_date, extracted_time),
        "turvo_start_time": format_turvo_stop_start_time(extracted_date, extracted_time),
    }
