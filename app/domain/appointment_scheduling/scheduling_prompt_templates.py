"""LangSmith scheduling optimization prompt variable builders."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


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
