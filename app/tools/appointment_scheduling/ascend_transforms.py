"""Pure Ascend payload transforms for appointment scheduling."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def _parse_datetime(iso_date_string: Any) -> dict[str, str | None]:
    if not iso_date_string:
        return {"date": None, "time": None}
    try:
        dt = datetime.fromisoformat(str(iso_date_string).replace("Z", "+00:00"))
        return {"date": dt.strftime("%m/%d/%Y"), "time": dt.strftime("%H:%M")}
    except (TypeError, ValueError):
        return {"date": None, "time": None}


def pickup_dropoff_from_ascend_shipment(api_response: dict[str, Any]) -> dict[str, Any]:
    if not api_response:
        return {"error": "API response is null or undefined"}
    shipment_stops = api_response.get("shipmentStops") or []
    if len(shipment_stops) < 2:
        return {"error": "Insufficient shipment stops data"}
    pickup_stop = shipment_stops[0]
    dropoff_stop = shipment_stops[1]
    pickup_dt = _parse_datetime(pickup_stop.get("appointmentStart"))
    raw_rate = str(api_response.get("totalCharge") or "").strip()
    cleaned_rate_str = raw_rate.replace("$", "").replace(",", "")
    if not cleaned_rate_str:
        return {"error": "Total charge not found in API response"}
    try:
        cleaned_rate = float(cleaned_rate_str)
    except ValueError:
        cleaned_rate = 0.0
    return {
        "pickup_data": {
            "date": pickup_dt["date"],
            "time": pickup_dt["time"],
            "location": pickup_stop.get("stopName") or pickup_stop.get("warehouseName") or "",
            "zipcode": pickup_stop.get("zipCode") or "",
            "state_name": pickup_stop.get("state") or "",
        },
        "dropoff_data": {
            "location": dropoff_stop.get("stopName") or dropoff_stop.get("warehouseName") or "",
            "zipcode": dropoff_stop.get("zipCode") or "",
            "state_name": dropoff_stop.get("state") or "",
        },
        "raw_rate": raw_rate,
        "cleaned_rate": cleaned_rate,
        "miles": float(api_response.get("totalMiles") or 0),
        "po_number": pickup_stop.get("poNumbers") or "",
        "pallet_count": int(pickup_stop.get("stopOrderTotalPallets") or 0),
        "weight_lbs": int(pickup_stop.get("stopOrderTotalWeight") or 0),
        "weight_units": pickup_stop.get("stopOrderTotalWeightUnit") or "",
        "pro_number": api_response.get("proNumber") or "",
    }


def llm_location_input_from_pickup_dropoff(pickup_dropoff: dict[str, Any]) -> dict[str, Any]:
    pickup = pickup_dropoff.get("pickup_data") or {}
    dropoff = pickup_dropoff.get("dropoff_data") or {}
    if not isinstance(pickup, dict):
        pickup = {}
    if not isinstance(dropoff, dict):
        dropoff = {}
    return {
        "pickup_location": pickup.get("location", ""),
        "dropoff_location": dropoff.get("location", ""),
        "pickup_state": pickup.get("state_name", ""),
        "dropoff_state": dropoff.get("state_name", ""),
        "startDateInput": pickup.get("date", ""),
        "startTimeInput": pickup.get("time", ""),
        "miles": pickup_dropoff.get("miles", 0),
    }


def normalize_availability_slots(
    appointment_details: list[dict[str, Any]] | dict[str, Any] | None,
    base_date_mm_dd_yyyy: str,
    office_code: str,
    *,
    fetch_slots,
) -> dict[str, Any]:
    """Build normalized availability map using injected ``fetch_slots(loc_id_ref, iso_date, office_code)``."""
    details = appointment_details or []
    if isinstance(details, dict):
        details = [details]
    if not details:
        return {"error": "Appointment details missing", "availability": {}, "total_dates": 0}

    first = details[0] if isinstance(details[0], dict) else {}
    location_ref = first.get("warehouse") if isinstance(first, dict) else None
    if not location_ref:
        return {
            "error": "Warehouse location reference not found in appointment details",
            "availability": {},
            "total_dates": 0,
        }

    try:
        base_date = datetime.strptime(base_date_mm_dd_yyyy.strip(), "%m/%d/%Y").date()
    except ValueError:
        return {"error": "Invalid base pickup date", "availability": {}, "total_dates": 0}

    availability: dict[str, Any] = {}
    checked = 0
    current = base_date
    while checked < 21 and len(availability) < 5:
        if current.weekday() >= 5:
            current += timedelta(days=1)
            continue
        iso_date = current.strftime("%Y-%m-%d")
        raw = fetch_slots(str(location_ref), iso_date, office_code)
        slots: list[str] = []
        if isinstance(raw, dict):
            docks = raw.get("docks") or raw.get("slots") or []
            if isinstance(docks, list):
                for dock in docks:
                    if not isinstance(dock, dict):
                        continue
                    for key in ("startTime", "time", "slotTime"):
                        val = dock.get(key)
                        if val:
                            slots.append(str(val))
        if slots:
            availability[current.strftime("%m/%d/%Y")] = {
                "pcs_format": current.strftime("%m/%d/%Y"),
                "times": slots,
            }
        current += timedelta(days=1)
        checked += 1

    return {
        "availability": availability,
        "total_dates": len(availability),
        "location_ref": location_ref,
    }
