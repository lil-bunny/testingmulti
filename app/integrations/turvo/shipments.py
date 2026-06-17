"""Turvo Public API shipment endpoints.

Each function is a thin wrapper around ``TurvoApiClient`` (``public_api_client``) —
no auth/retry logic should live here.

Shipment-scoped POD checks use ``GET /v1/documents/list`` — see
``app.integrations.turvo.documents``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.domain.shipment_display import ShipmentDisplayFields
from app.domain.shipment_route_locations import (
    active_route_stops,
    last_active_route_stop,
)
from app.domain.spreadsheet_cells import clean_cell_value
from app.integrations.pgeocode.state_lookup import lookup_state
from app.integrations.turvo.documents import check_pod_by_shipment_id
from app.integrations.turvo.public_api_client import TurvoApiClient


def global_route_stops_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return ``details.globalRoute`` from a Turvo shipment API payload."""
    if not isinstance(payload, dict):
        return []
    details = payload.get("details")
    if not isinstance(details, dict):
        return []
    route = details.get("globalRoute")
    if not isinstance(route, list):
        return []
    return [s for s in route if isinstance(s, dict)]


def _required_str(val: Any) -> str:
    cleaned = clean_cell_value(val)
    if cleaned is None:
        return ""
    return str(cleaned)


def _optional_str(val: Any) -> str | None:
    cleaned = clean_cell_value(val)
    if cleaned is None:
        return None
    s = str(cleaned).strip()
    return s if s else None


def _postal_from_address(address: dict[str, Any]) -> str:
    return _required_str(address.get("zip") or address.get("zipCode"))


def _stop_location_key(stop: dict[str, Any]) -> str | None:
    """Turvo globalRoute stop id for matching customerOrder.route globalShipLocationId."""
    raw = stop.get("id")
    if raw is None:
        return None
    key = str(raw).strip()
    return key if key else None


def _iter_customer_order_routes(details: dict[str, Any]) -> list[dict[str, Any]]:
    orders = details.get("customerOrder")
    if not isinstance(orders, list):
        return []
    routes: list[dict[str, Any]] = []
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        route = order.get("route")
        if not isinstance(route, list):
            continue
        for item in route:
            if isinstance(item, dict) and not item.get("deleted"):
                routes.append(item)
    return routes


def postal_from_customer_order_route(
    details: dict[str, Any],
    global_route_stop: dict[str, Any],
) -> str | None:
    """Zip from ``customerOrder.route`` when ``globalRoute.address`` omits it."""
    stop_key = _stop_location_key(global_route_stop)
    if not stop_key:
        return None
    for route_stop in _iter_customer_order_routes(details):
        loc_id = route_stop.get("globalShipLocationId")
        if loc_id is None or str(loc_id).strip() != stop_key:
            continue
        address = route_stop.get("address")
        if not isinstance(address, dict):
            continue
        postal = _postal_from_address(address)
        return postal if postal else None
    return None


def delivery_address_from_global_route_stop(stop: dict[str, Any]) -> dict[str, Any] | None:
    """
    Map one Turvo ``globalRoute`` stop to canonical ``delivery_address`` JSON.

    Same keys as ``tenders.delivery_address`` / ``delivery_address_from_location_row``.
    Returns ``None`` when city or state is missing (FK linking may still proceed).
    """
    if not isinstance(stop, dict):
        return None
    address = stop.get("address")
    if not isinstance(address, dict):
        address = {}

    city = _required_str(address.get("city"))
    state_raw = _required_str(address.get("state"))
    if not city or not state_raw:
        return None

    location = stop.get("location")
    loc_name = ""
    if isinstance(location, dict):
        loc_name = _required_str(location.get("name"))

    name = _required_str(stop.get("name")) or loc_name
    country = _required_str(
        address.get("country") or address.get("countryCode") or address.get("countryName")
    )
    postal = _postal_from_address(address)
    state = (lookup_state(country or None, postal or None) or "").strip()
    if not state:
        state = state_raw

    return {
        "name": name,
        "name2": None,
        "address1": _required_str(address.get("line1")),
        "address2": _optional_str(address.get("line2")),
        "city": city,
        "state": state,
        "postal_code": postal,
        "country": country or "US",
    }


def _first_non_deleted_entity_name(
    orders: Any,
    entity_key: str,
) -> str | None:
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        entity = order.get(entity_key)
        if not isinstance(entity, dict):
            continue
        name = str(entity.get("name") or "").strip()
        if name:
            return name
    return None


_PICKUP_STOP_VALUE = "pickup"


@dataclass(frozen=True)
class PickupAppointment:
    at_utc: datetime
    timezone: str | None
    source: str


def _stop_type_value(stop: dict[str, Any]) -> str:
    stop_type = stop.get("stopType")
    if isinstance(stop_type, dict):
        raw = stop_type.get("value") or stop_type.get("key")
        if raw is not None and str(raw).strip():
            return str(raw).strip().lower()
    raw = stop.get("type")
    return str(raw).strip().lower() if raw is not None else ""


def _is_pickup_stop(stop: dict[str, Any]) -> bool:
    return _stop_type_value(stop) == _PICKUP_STOP_VALUE


def _datetime_from_appointment_dict(
    appt: dict[str, Any],
    *,
    default_timezone: str | None = None,
) -> tuple[datetime | None, str | None]:
    if not isinstance(appt, dict):
        return None, default_timezone
    tz = _optional_str(appt.get("timeZone") or appt.get("timezone")) or default_timezone
    for key in ("date", "start"):
        raw = appt.get(key)
        if raw is None or not str(raw).strip():
            continue
        text = str(raw).strip()
        try:
            if "T" in text:
                dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc), tz
            parsed_date = date.fromisoformat(text[:10])
            return datetime.combine(parsed_date, datetime.min.time(), tzinfo=timezone.utc), tz
        except ValueError:
            continue
    return None, tz


def _datetime_from_stop_appointment(
    stop: dict[str, Any],
) -> tuple[datetime | None, str | None]:
    default_tz = _optional_str(stop.get("timezone") or stop.get("timeZone"))
    appt = stop.get("appointment")
    if isinstance(appt, dict):
        dt, tz = _datetime_from_appointment_dict(appt, default_timezone=default_tz)
        if dt is not None:
            return dt, tz
    return None, default_tz


def _pickup_stop_from_global_route(payload: dict[str, Any]) -> dict[str, Any] | None:
    for stop in active_route_stops(global_route_stops_from_payload(payload)):
        if _is_pickup_stop(stop):
            return stop
    route_stops = active_route_stops(global_route_stops_from_payload(payload))
    return route_stops[0] if route_stops else None


def _pickup_stop_from_customer_order_routes(details: dict[str, Any]) -> dict[str, Any] | None:
    for route_stop in _iter_customer_order_routes(details):
        if _is_pickup_stop(route_stop):
            return route_stop
    routes = _iter_customer_order_routes(details)
    return routes[0] if routes else None


def pickup_appointment_from_payload(payload: dict[str, Any]) -> PickupAppointment | None:
    """
    Confirmed pickup appointment from Turvo shipment JSON.

    Primary: ``globalRoute`` pickup stop ``appointment.date``.
    """
    if not isinstance(payload, dict):
        return None
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    stop = _pickup_stop_from_global_route(payload)
    if stop is not None:
        dt, tz = _datetime_from_stop_appointment(stop)
        if dt is not None:
            return PickupAppointment(
                at_utc=dt,
                timezone=tz,
                source="globalRoute.appointment.date",
            )

    route_stop = _pickup_stop_from_customer_order_routes(details)
    if route_stop is not None:
        dt, tz = _datetime_from_stop_appointment(route_stop)
        if dt is not None:
            return PickupAppointment(
                at_utc=dt,
                timezone=tz,
                source="customerOrder.route.appointment.start",
            )

    start_date = details.get("startDate")
    if isinstance(start_date, dict):
        dt, tz = _datetime_from_appointment_dict(start_date)
        if dt is not None:
            return PickupAppointment(
                at_utc=dt,
                timezone=tz,
                source="details.startDate.date",
            )
    return None


TL_TRANSPORTATION_MODE_KEY = "24105"
COVERED_STATUS_CODE_KEY = "2102"
_EXCLUDED_CARRIER_NAME_SUBSTRINGS = ("a&v palacio truck lines", "convoy")


def driver_request_eligible_from_payload(payload: dict[str, Any]) -> str | None:
    """
    Return skip_reason when driver-request workflow must not start; None if eligible.

    Requires TL mode (24105), Turvo Covered status (2102), and non-excluded carrier.
    """
    if not isinstance(payload, dict):
        return "shipment_not_in_state"
    details = payload.get("details")
    if not isinstance(details, dict):
        return "shipment_not_in_state"

    transportation = details.get("transportation")
    mode_key = ""
    if isinstance(transportation, dict):
        mode = transportation.get("mode")
        if isinstance(mode, dict):
            mode_key = str(mode.get("key") or "").strip()
    if mode_key != TL_TRANSPORTATION_MODE_KEY:
        return "transportation_mode_not_tl"

    status = details.get("status")
    status_key = ""
    if isinstance(status, dict):
        code = status.get("code")
        if isinstance(code, dict):
            status_key = str(code.get("key") or "").strip()
    if status_key != COVERED_STATUS_CODE_KEY:
        return "shipment_not_covered"

    carrier_orders = details.get("carrierOrder")
    if isinstance(carrier_orders, list):
        for order in carrier_orders:
            if not isinstance(order, dict) or order.get("deleted"):
                continue
            carrier = order.get("carrier")
            if not isinstance(carrier, dict):
                continue
            name = str(carrier.get("name") or "").lower()
            if any(substr in name for substr in _EXCLUDED_CARRIER_NAME_SUBSTRINGS):
                return "excluded_carrier"

    return None


def _stop_has_actual_pickup(stop: dict[str, Any]) -> bool:
    actual = stop.get("actual")
    if not isinstance(actual, dict):
        return False
    for key in ("checkIn", "check_in", "arrival", "date", "start"):
        raw = actual.get(key)
        if raw is not None and str(raw).strip():
            return True
    return False


def _active_driver_entry(entry: dict[str, Any]) -> bool:
    if not isinstance(entry, dict) or entry.get("deleted"):
        return False
    return any(
        str(entry.get(field) or "").strip()
        for field in ("id", "name", "phone", "email")
    )


def driver_assigned_from_payload(payload: dict[str, Any]) -> bool:
    """True when Turvo shows driver assigned or pickup already executed."""
    if not isinstance(payload, dict):
        return False
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    pickup_stop = _pickup_stop_from_global_route(payload)
    if pickup_stop is not None and _stop_has_actual_pickup(pickup_stop):
        return True

    carrier_orders = details.get("carrierOrder")
    if not isinstance(carrier_orders, list):
        return False
    for order in carrier_orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        for key in ("driver", "drivers", "primaryDriver"):
            raw = order.get(key)
            if isinstance(raw, dict) and _active_driver_entry(raw):
                return True
            if isinstance(raw, list):
                for item in raw:
                    if _active_driver_entry(item):
                        return True
    return False


def _date_from_stop_appointment(stop: dict[str, Any]) -> date | None:
    appt = stop.get("appointment")
    if not isinstance(appt, dict):
        return None
    for key in ("date", "start"):
        raw = appt.get(key)
        if raw is None or not str(raw).strip():
            continue
        text = str(raw).strip()
        try:
            if "T" in text:
                return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
            return date.fromisoformat(text[:10])
        except ValueError:
            continue
    return None


def _delivery_date_from_customer_order_routes(details: dict[str, Any]) -> date | None:
    orders = details.get("customerOrder")
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        route = order.get("route")
        if not isinstance(route, list):
            continue
        active = [s for s in route if isinstance(s, dict) and not s.get("deleted")]
        if not active:
            continue
        parsed = _date_from_stop_appointment(active[-1])
        if parsed is not None:
            return parsed
    return None


def shipment_display_fields_from_payload(payload: dict[str, Any]) -> ShipmentDisplayFields:
    """Map Turvo GET ``/shipments/{id}`` JSON to display columns for ``shipments``."""
    if not isinstance(payload, dict):
        return ShipmentDisplayFields()

    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    customer_name = _first_non_deleted_entity_name(
        details.get("customerOrder"),
        "customer",
    )
    carrier_name = _first_non_deleted_entity_name(
        details.get("carrierOrder"),
        "carrier",
    )

    delivery_date: date | None = None
    route_stops = active_route_stops(global_route_stops_from_payload(payload))
    if route_stops:
        try:
            delivery_date = _date_from_stop_appointment(
                last_active_route_stop(route_stops)
            )
        except ValueError:
            delivery_date = None
    if delivery_date is None:
        delivery_date = _delivery_date_from_customer_order_routes(details)

    return ShipmentDisplayFields(
        carrier_name=carrier_name,
        customer_name=customer_name,
        delivery_date=delivery_date,
    )


async def get_shipment(
    tenant_slug: str,
    shipment_id: Any,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """GET /v1/shipments/{shipmentId} — full shipment details for the given id."""
    if not shipment_id:
        raise ValueError("shipment_id is required")
    slug = (tenant_slug or "").strip()
    if not slug:
        raise ValueError("tenant_slug is required")
    api = client or TurvoApiClient()
    return await api.request(
        slug,
        "GET",
        f"/shipments/{shipment_id}",
    )
