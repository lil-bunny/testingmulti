"""Pure PO resolution for appointment scheduling (no I/O)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.utils import is_costco_customer
from app.domain.shipment_route_locations import active_route_stops

_DELIVERY_STOP_VALUE = "delivery"


def resolve_scheduling_po_number(
    *,
    customer_name: str,
    turvo_payload: dict | None,
    pickup_dropoff: dict | None,
) -> str:
    if is_costco_customer(customer_name):
        return _delivery_po_from_turvo_payload(turvo_payload)
    return _normalize_po_value((pickup_dropoff or {}).get("po_number"))


def _normalize_po_value(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, list):
        parts = [str(item).strip() for item in raw if str(item).strip()]
        return ",".join(parts)
    return str(raw).strip()


def _global_route_stops_from_payload(payload: dict | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    details = payload.get("details")
    if isinstance(details, dict):
        route = details.get("globalRoute")
        if isinstance(route, list):
            return [s for s in route if isinstance(s, dict)]
    global_route = payload.get("global_route")
    if isinstance(global_route, dict):
        ship_locations = global_route.get("ship_locations")
        if isinstance(ship_locations, list):
            return [s for s in ship_locations if isinstance(s, dict)]
    return []


def _stop_type_value(stop: dict[str, Any]) -> str:
    stop_type = stop.get("stopType")
    if isinstance(stop_type, dict):
        raw = stop_type.get("value") or stop_type.get("key")
        if raw is not None and str(raw).strip():
            return str(raw).strip().lower()
    raw = stop.get("type")
    return str(raw).strip().lower() if raw is not None else ""


def _is_delivery_stop(stop: dict[str, Any]) -> bool:
    return _stop_type_value(stop) == _DELIVERY_STOP_VALUE


def _po_from_stop(stop: dict[str, Any]) -> str:
    for key in ("poNumbers", "purchase_orders"):
        normalized = _normalize_po_value(stop.get(key))
        if normalized:
            return normalized
    return ""


def _delivery_po_from_turvo_payload(payload: dict | None) -> str:
    for stop in reversed(active_route_stops(_global_route_stops_from_payload(payload))):
        if not _is_delivery_stop(stop):
            continue
        po = _po_from_stop(stop)
        if po:
            return po
    return ""
