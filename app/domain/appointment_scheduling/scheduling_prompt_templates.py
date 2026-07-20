"""LangSmith scheduling optimization prompt variables and inline fallback."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

SCHEDULING_OPTIMIZATION_SYSTEM_TEMPLATE = """You are a logistics scheduling expert optimizing pickup times and delivery dates for freight shipments.

SHIPMENT DETAILS:
- Distance: {miles} miles
- Pickup Location: {pickup_location}
- Dropoff Location: {dropoff_location}
- Dropoff State: {dropoff_state}
- Customer: {customer_name}
- Extra rules (override others on conflict): {special_rule}
- Is Chewy Customer: {is_chewy_customer}

BASE PICKUP CONTEXT (SOURCE OF TRUTH FOR INITIAL CALCULATION):
- Base Pickup Date: {base_pickup_date}
- Base Pickup Time: {base_pickup_time}

AVAILABLE PICKUP TIMES:
{availability_text}

Follow the standard T3RA scheduling rule chain: baseline pickup lock, customer-specific windows (CHEWY/AFCO/PETCO), distance-based transit days, initial delivery from base pickup, conditional weekend reschedule, final validation.

OUTPUT FORMAT (JSON only, no other text):
{{
  "selected_pickup_date": "YYYY-MM-DD",
  "selected_pickup_time": "HH:MM",
  "pcs_pickup_date": "MM/DD/YYYY",
  "calculated_delivery_date": "MM/DD/YYYY",
  "calculated_delivery_weekday": "MONDAY",
  "transit_days": 0,
  "reasoning": "step-by-step explanation",
  "time_category": "morning",
  "weekend_shifted": false
}}"""

SCHEDULING_OPTIMIZATION_USER_TEMPLATE = (
    "Analyze the data and return ONLY valid JSON.\n\nStructured input:\n{scheduling_input_json}"
)


def format_availability_text(availability: dict[str, Any]) -> str:
    slots = availability.get("availability") if isinstance(availability, dict) else {}
    if not isinstance(slots, dict) or not slots:
        return "(no availability slots)"
    lines: list[str] = []
    for date_key, data in sorted(slots.items()):
        if not isinstance(data, dict):
            continue
        times = data.get("times") or []
        time_text = ", ".join(str(t) for t in times if t)
        pcs = data.get("pcs_format") or date_key
        day_name = ""
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                day_name = datetime.strptime(str(pcs).strip(), fmt).strftime("%A").upper()
                break
            except ValueError:
                continue
        suffix = f" - {day_name}" if day_name else ""
        lines.append(f"- {date_key} ({pcs}){suffix}: {time_text or 'no times'}")
    return "\n".join(lines) if lines else "(no availability slots)"


def scheduling_optimization_prompt_variables(
    *,
    location_input: dict[str, Any],
    availability: dict[str, Any],
    customer_name: str,
    special_rule: str = "None",
) -> dict[str, str]:
    name = str(customer_name or "").strip()
    return {
        "miles": str(location_input.get("miles") or 0),
        "pickup_location": str(location_input.get("pickup_location") or ""),
        "dropoff_location": str(location_input.get("dropoff_location") or ""),
        "dropoff_state": str(location_input.get("dropoff_state") or "Unknown"),
        "customer_name": name or "Unknown",
        "special_rule": special_rule or "None",
        "is_chewy_customer": "true" if "CHEWY" in name.upper() else "false",
        "base_pickup_date": str(location_input.get("startDateInput") or "UNKNOWN"),
        "base_pickup_time": str(location_input.get("startTimeInput") or "UNKNOWN"),
        "availability_text": format_availability_text(availability),
        "scheduling_input_json": json.dumps(
            {"location_input": location_input, "availability": availability},
            ensure_ascii=False,
        ),
    }


def render_inline_scheduling_optimization_prompts(
    variables: dict[str, str],
) -> tuple[str, str]:
    return (
        SCHEDULING_OPTIMIZATION_SYSTEM_TEMPLATE.format(**variables),
        SCHEDULING_OPTIMIZATION_USER_TEMPLATE.format(**variables),
    )
