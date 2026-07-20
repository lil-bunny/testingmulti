"""Pure Ascend pickup appointment update planning for weekend-shifted confirm."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class AscendPickupUpdatePlan:
    should_apply: bool = False
    appointment_id: str | None = None
    update_body: dict[str, Any] | None = None
    turvo_pickup_start_time: str | None = None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1]
    if "+" in text[10:] or "-" in text[10:]:
        text = text[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _split_time_str(value: Any) -> str | None:
    if not value:
        return None
    text = str(value).strip()
    if ":" not in text:
        return text
    if text.count(":") == 1:
        return f"{text}:00"
    if text.count(":") >= 2 and len(text) >= 5:
        return f"{text[:5]}:00"
    return text


def _normalize_appointments(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("data", "result", "appointments"):
            nested = raw.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
    return []


def _choose_appointment_row(appointments: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in appointments:
        stop_no = row.get("stopNumber")
        if stop_no is not None and str(stop_no) == "1":
            return row
    for row in appointments:
        request_type = row.get("requestType")
        if request_type and "LIVE_LOAD" in str(request_type):
            return row
    return appointments[0] if appointments else None


def plan_ascend_pickup_update(
    appointments: Any,
    selected_date: Any,
    selected_time: Any,
) -> AscendPickupUpdatePlan:
    """Build Ascend PUT body and Turvo pickup time when LLM pickup changed."""
    empty = AscendPickupUpdatePlan()
    if not selected_date or not selected_time:
        return empty

    rows = _normalize_appointments(appointments)
    if not rows:
        return empty

    chosen = _choose_appointment_row(rows)
    if chosen is None:
        return empty

    appointment_id = chosen.get("appointmentId") or chosen.get("id") or chosen.get("stopId")
    if appointment_id is None:
        return empty

    existing_start = _parse_datetime(chosen.get("startTime") or chosen.get("appointmentStart"))
    existing_end = _parse_datetime(chosen.get("endTime") or chosen.get("appointmentEnd"))

    normalized_time = _split_time_str(selected_time)
    if not normalized_time:
        return empty

    parts = str(normalized_time).strip().split(":")
    if len(parts) >= 2:
        normalized_time = f"{parts[0]}:{parts[1]}:00"

    date_str = str(selected_date).strip()
    new_start_iso = f"{date_str}T{normalized_time}"
    new_start = _parse_datetime(new_start_iso)
    if new_start is None:
        return empty

    if existing_start:
        same_date = existing_start.date() == new_start.date()
        same_time = (existing_start.hour, existing_start.minute) == (
            new_start.hour,
            new_start.minute,
        )
        if same_date and same_time:
            return empty
    else:
        return empty

    duration = timedelta(hours=1)
    if existing_start and existing_end and existing_end > existing_start:
        duration = existing_end - existing_start
    new_end = new_start + duration

    update_body = dict(chosen)
    update_body["appointmentId"] = appointment_id
    update_body["startTime"] = new_start.strftime("%Y-%m-%dT%H:%M:%S")
    update_body["endTime"] = new_end.strftime("%Y-%m-%dT%H:%M:%S")
    update_body["appointmentStart"] = update_body["startTime"].replace("T", " ")
    update_body["appointmentEnd"] = update_body["endTime"].replace("T", " ")

    for key in ("dockNumber", "stopNumber"):
        if key in update_body and update_body[key] is not None:
            try:
                update_body[key] = int(str(update_body[key]).strip())
            except ValueError:
                pass

    turvo_time = f"{date_str} {normalized_time}"
    return AscendPickupUpdatePlan(
        should_apply=True,
        appointment_id=str(appointment_id),
        update_body=update_body,
        turvo_pickup_start_time=turvo_time,
    )
