"""Turvo Public API shipment endpoints.

Each function is a thin wrapper around ``TurvoApiClient`` (``public_api_client``) —
no auth/retry logic should live here.

Shipment-scoped POD checks use ``GET /v1/documents/list`` — see
``app.integrations.turvo.documents``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Optional

from app.domain.shipment_display import ShipmentDisplayFields
from app.domain.shipment_route_locations import (
    active_route_stops,
    is_multi_stop_route,
    last_active_route_stop,
)
from app.domain.spreadsheet_cells import clean_cell_value
from app.integrations.pgeocode.state_lookup import (
    lookup_postal,
    lookup_state,
    lookup_state_display_name,
)
from app.integrations.turvo.public_api_client import TurvoApiClient

# Turvo lookup keys (Public API docs + sandbox verification).
TRACKING_METHOD_NONE = {"key": "31300", "value": "none"}
TRACKING_METHOD_TURVO_APP = {"key": "31301", "value": "Turvo Driver app"}
DRIVER_TYPE_SINGLE = {"key": "20020", "value": "Single driver"}


def global_route_stops_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized route stops from camelCase or export-style Turvo payloads."""
    if not isinstance(payload, dict):
        return []
    details = payload.get("details")
    if not isinstance(details, dict):
        return []
    route = details.get("globalRoute")
    if isinstance(route, list):
        return [s for s in route if isinstance(s, dict)]

    exported_route = details.get("global_route")
    exported_stops = (
        exported_route.get("ship_locations") if isinstance(exported_route, dict) else None
    )
    if not isinstance(exported_stops, list):
        return []

    normalized: list[dict[str, Any]] = []
    for stop in exported_stops:
        if not isinstance(stop, dict):
            continue
        stop_type = stop.get("type") if isinstance(stop.get("type"), dict) else {}
        address = stop.get("address") if isinstance(stop.get("address"), dict) else {}
        city = address.get("city")
        state = address.get("state")
        country = address.get("country")
        normalized.append(
            {
                "id": stop.get("globalRouteStopId") or stop.get("global_ship_location_id"),
                "name": stop.get("name"),
                "stopType": {"key": stop_type.get("key"), "value": stop_type.get("value")},
                "timezone": stop.get("timezone"),
                "address": {
                    "line1": address.get("line1"),
                    "city": city.get("name") if isinstance(city, dict) else city,
                    "state": state.get("name") if isinstance(state, dict) else state,
                    "countryCode": (
                        country.get("code") if isinstance(country, dict) else address.get("countryISO")
                    ),
                },
                "poNumbers": stop.get("purchase_orders"),
                "notes": stop.get("instructions"),
                "deleted": stop.get("deleted"),
            }
        )
    return normalized


def is_multi_stop_shipment(payload: dict[str, Any]) -> bool:
    return is_multi_stop_route(global_route_stops_from_payload(payload))


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


def location_insert_row_from_route_stop(
    stop: dict[str, Any],
    shipment_details: dict[str, Any] | None = None,
) -> dict[str, str | None] | None:
    """
    Build ``locations`` insert fields from one Turvo ``globalRoute`` stop.

    Uses stop ``address``, then ``customerOrder.route`` zip, then pgeocode.
    Returns ``None`` when city or state code is missing.
    """
    if not isinstance(stop, dict):
        return None
    address = stop.get("address")
    if not isinstance(address, dict):
        address = {}

    city = _required_str(address.get("city"))
    state_code = _required_str(address.get("state"))
    if not city or not state_code:
        return None

    country = _required_str(
        address.get("countryCode") or address.get("country") or address.get("countryName")
    ) or "US"

    postal = _postal_from_address(address) or None
    if not postal and isinstance(shipment_details, dict):
        postal = postal_from_customer_order_route(shipment_details, stop) or None
    if not postal:
        postal = lookup_postal(country, city, state_code) or None

    state = lookup_state_display_name(
        country,
        postal,
        state_code_fallback=state_code,
    )

    return {
        "city": city,
        "state": state,
        "state_code": state_code,
        "postal_code": postal,
        "country": country,
    }


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


def customer_name_from_payload(payload: dict[str, Any]) -> str | None:
    """First non-deleted ``customerOrder[].customer.name`` from a Turvo shipment GET."""
    details = payload.get("details") if isinstance(payload, dict) else None
    if not isinstance(details, dict):
        return None
    return _first_non_deleted_entity_name(details.get("customerOrder"), "customer")


def _delivery_location_name_from_customer_order(details: dict[str, Any]) -> str | None:
    """Repo A check_reply: last item deliveryLocation name on first active customer order."""
    orders = details.get("customerOrder") or details.get("customer_orders") or []
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        items = order.get("items") or []
        if not isinstance(items, list) or not items:
            continue
        last_item = items[-1] if isinstance(items[-1], dict) else None
        if not last_item:
            continue
        locations = (
            last_item.get("deliveryLocation")
            or last_item.get("delivery_location")
            or []
        )
        if not isinstance(locations, list) or not locations:
            continue
        location = locations[0] if isinstance(locations[0], dict) else None
        if not location:
            continue
        name = str(location.get("name") or location.get("stop_name") or "").strip()
        if name:
            return name
    return None


def delivery_stop_name_from_payload(payload: dict[str, Any]) -> str | None:
    """Operational delivery stop name: active globalRoute Delivery stop, then customerOrder fallback."""
    if not isinstance(payload, dict):
        return None
    from_route = _delivery_stop_name_from_global_route(payload)
    if from_route:
        return from_route
    details = payload.get("details")
    if isinstance(details, dict):
        return _delivery_location_name_from_customer_order(details)
    return None


def pickup_stop_name_from_payload(payload: dict[str, Any]) -> str | None:
    """Turvo globalRoute stop name for pickup appointment updates."""
    if not isinstance(payload, dict):
        return None
    stop = _pickup_stop_from_global_route(payload)
    if stop is not None:
        name = str(stop.get("name") or "").strip()
        if name:
            return name
    details = payload.get("details")
    if isinstance(details, dict):
        route_stop = _pickup_stop_from_customer_order_routes(details)
        if route_stop is not None:
            name = str(route_stop.get("name") or "").strip()
            if name:
                return name
    return None


def delivery_date_only_from_payload(payload: dict[str, Any]) -> str | None:
    """Normalized ``YYYY-MM-DD`` delivery date for confirm-phase 0001 rule."""
    from app.tools.appointment_scheduling.dates import normalize_date_only

    if not isinstance(payload, dict):
        return None
    delivery_dt, _ = delivery_appointment_from_payload(payload)
    if delivery_dt is not None:
        return delivery_dt.strftime("%Y-%m-%d")
    details = payload.get("details")
    if isinstance(details, dict):
        end_date = details.get("endDate") or details.get("end_date") or {}
        if isinstance(end_date, dict):
            return normalize_date_only(
                end_date.get("userDate") or end_date.get("date")
            )
    return None


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
_DELIVERY_STOP_VALUE = "delivery"


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


def _is_delivery_stop(stop: dict[str, Any]) -> bool:
    return _stop_type_value(stop) == _DELIVERY_STOP_VALUE


def _delivery_stop_name_from_global_route(payload: dict[str, Any]) -> str | None:
    for stop in reversed(active_route_stops(global_route_stops_from_payload(payload))):
        if not _is_delivery_stop(stop):
            continue
        name = str(stop.get("name") or "").strip()
        if name:
            return name
    return None


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


def _delivery_stop_from_customer_order_routes(
    details: dict[str, Any],
) -> dict[str, Any] | None:
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
        if active:
            return active[-1]
    return None


def delivery_appointment_from_payload(
    payload: dict[str, Any],
) -> tuple[datetime | None, str | None]:
    """Delivery appointment from last active route stop (globalRoute, then customerOrder)."""
    if not isinstance(payload, dict):
        return None, None
    details = payload.get("details")
    if not isinstance(details, dict):
        details = {}

    route_stops = active_route_stops(global_route_stops_from_payload(payload))
    if route_stops:
        try:
            dt, tz = _datetime_from_stop_appointment(last_active_route_stop(route_stops))
            if dt is not None:
                return dt, tz
        except ValueError:
            pass

    route_stop = _delivery_stop_from_customer_order_routes(details)
    if route_stop is not None:
        dt, tz = _datetime_from_stop_appointment(route_stop)
        if dt is not None:
            return dt, tz
    return None, None


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
    if any(
        str(entry.get(field) or "").strip()
        for field in ("id", "name", "phone", "email")
    ):
        return True
    ctx = entry.get("context")
    if isinstance(ctx, dict) and str(ctx.get("id") or ctx.get("name") or "").strip():
        return True
    return False


def _driver_phone_from_entry(entry: dict[str, Any]) -> str | None:
    raw = entry.get("phone")
    if isinstance(raw, str):
        text = raw.strip()
        return text or None
    if isinstance(raw, dict):
        number = raw.get("number")
        if number is not None:
            text = str(number).strip()
            return text or None
    return None


def _driver_name_from_entry(entry: dict[str, Any]) -> str | None:
    name = entry.get("name")
    if name is not None and str(name).strip():
        return str(name).strip()
    ctx = entry.get("context")
    if isinstance(ctx, dict):
        ctx_name = ctx.get("name")
        if ctx_name is not None and str(ctx_name).strip():
            return str(ctx_name).strip()
    return None


def _iter_active_driver_entries(order: dict[str, Any]):
    for key in ("driver", "drivers", "primaryDriver"):
        raw = order.get(key)
        if isinstance(raw, dict) and _active_driver_entry(raw):
            yield raw
        elif isinstance(raw, list):
            for item in raw:
                if _active_driver_entry(item):
                    yield item


def assigned_driver_contact_from_payload(payload: dict[str, Any]) -> dict[str, str | None]:
    """Name and phone from the first active driver embed on a Turvo shipment payload."""
    if not isinstance(payload, dict):
        return {"name": None, "phone": None}
    details = payload.get("details")
    if not isinstance(details, dict):
        return {"name": None, "phone": None}
    carrier_orders = details.get("carrierOrder")
    if not isinstance(carrier_orders, list):
        return {"name": None, "phone": None}
    for order in carrier_orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        for entry in _iter_active_driver_entries(order):
            return {
                "name": _driver_name_from_entry(entry),
                "phone": _driver_phone_from_entry(entry),
            }
    return {"name": None, "phone": None}


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

    pickup_date: datetime | None = None
    pickup_timezone: str | None = None
    pickup = pickup_appointment_from_payload(payload)
    if pickup is not None:
        pickup_date = pickup.at_utc
        pickup_timezone = pickup.timezone

    delivery_date, delivery_timezone = delivery_appointment_from_payload(payload)

    return ShipmentDisplayFields(
        carrier_name=carrier_name,
        customer_name=customer_name,
        pickup_date=pickup_date,
        pickup_timezone=pickup_timezone,
        delivery_date=delivery_date,
        delivery_timezone=delivery_timezone,
    )


def appointment_scheduling_display_fields_from_payload(
    payload: dict[str, Any],
) -> ShipmentDisplayFields:
    """Display fields for appointment scheduling: ``customer_name`` is delivery stop, not bill-to."""
    fields = shipment_display_fields_from_payload(payload)
    stop = delivery_stop_name_from_payload(payload)
    if stop:
        return replace(fields, customer_name=stop)
    return fields


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


def driver_contact_ids_from_carrier_order(order: dict[str, Any]) -> list[int]:
    """Non-deleted ``drivers[]`` / ``driver`` contact ids on one carrier order."""
    if not isinstance(order, dict) or order.get("deleted"):
        return []
    ids: list[int] = []
    seen: set[int] = set()
    for key in ("drivers", "driver", "primaryDriver"):
        raw = order.get(key)
        entries: list[dict[str, Any]] = []
        if isinstance(raw, list):
            entries = [e for e in raw if isinstance(e, dict)]
        elif isinstance(raw, dict):
            entries = [raw]
        for entry in entries:
            if entry.get("deleted"):
                continue
            cid: Any = None
            context = entry.get("context")
            if isinstance(context, dict):
                cid = context.get("id")
            if cid is None:
                cid = entry.get("driverId")
            if cid is None:
                continue
            try:
                contact_id = int(cid)
            except (TypeError, ValueError):
                continue
            if contact_id not in seen:
                seen.add(contact_id)
                ids.append(contact_id)
    return ids


def driver_contact_ids_from_shipment(payload: dict[str, Any], *, carrier_id: int) -> list[int]:
    """Contact ids referenced on the active carrier order for ``carrier_id``."""
    order = first_active_carrier_order(payload)
    if not order:
        return []
    order_carrier_id, _ = carrier_from_order(order)
    if order_carrier_id != carrier_id:
        return []
    return driver_contact_ids_from_carrier_order(order)


def first_active_carrier_order(payload: dict[str, Any]) -> dict[str, Any] | None:
    details = payload.get("details") if isinstance(payload, dict) else None
    orders = details.get("carrierOrder") if isinstance(details, dict) else None
    if not isinstance(orders, list):
        return None
    for order in orders:
        if isinstance(order, dict) and not order.get("deleted"):
            return order
    return None


def carrier_from_order(order: dict[str, Any]) -> tuple[int | None, str | None]:
    carrier = order.get("carrier") if isinstance(order, dict) else None
    if not isinstance(carrier, dict):
        return None, None
    try:
        carrier_id = int(carrier.get("id")) if carrier.get("id") is not None else None
    except (TypeError, ValueError):
        carrier_id = None
    name = carrier.get("name")
    carrier_name = str(name).strip() if name else None
    return carrier_id, carrier_name


def segment_id_from_order(order: dict[str, Any]) -> str | None:
    for key in ("segmentId", "segmentID"):
        val = order.get(key)
        if val:
            return str(val)
    drivers = order.get("drivers")
    if isinstance(drivers, list):
        for d in drivers:
            if isinstance(d, dict) and d.get("segmentId"):
                return str(d["segmentId"])
    return None


def driver_assignment_row_ids_from_carrier_order(order: dict[str, Any]) -> list[str]:
    """Non-deleted ``drivers[]`` assignment row ids for Turvo ``_operation: 2`` delete."""
    if not isinstance(order, dict) or order.get("deleted"):
        return []
    ids: list[str] = []
    seen: set[str] = set()
    for key in ("drivers", "driver", "primaryDriver"):
        raw = order.get(key)
        entries: list[dict[str, Any]] = []
        if isinstance(raw, list):
            entries = [e for e in raw if isinstance(e, dict)]
        elif isinstance(raw, dict):
            entries = [raw]
        for entry in entries:
            if entry.get("deleted"):
                continue
            row_id = entry.get("id")
            if row_id is None:
                row_id = entry.get("driverAssignmentId")
            if row_id is None:
                continue
            text = str(row_id).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            ids.append(text)
    return ids


def _driver_add_entry(
    contact_id: int,
    *,
    segment_id: str | None,
    send_invite: bool,
) -> dict[str, Any]:
    driver_entry: dict[str, Any] = {
        "driverId": int(contact_id),
        "segmentSequence": 0,
        "segmentId": segment_id or "",
        "_operation": 0,
        "sendInvite": bool(send_invite),
        "trackingMethod": (
            TRACKING_METHOD_TURVO_APP if send_invite else TRACKING_METHOD_NONE
        ),
    }
    if send_invite:
        # Docs: sendInvite true only when trackingMethod is Turvo Driver app.
        driver_entry["driverType"] = DRIVER_TYPE_SINGLE
    return driver_entry


async def assign_driver_to_shipment(
    tenant_slug: str,
    shipment_id: Any,
    *,
    carrier_order_id: int,
    contact_id: int,
    segment_id: str | None = None,
    send_invite: bool = False,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """PUT /shipments/{id} — attach driver contact to active carrier order."""
    api = client or TurvoApiClient()
    sid = int(shipment_id) if str(shipment_id).isdigit() else shipment_id
    driver_entry = _driver_add_entry(
        contact_id,
        segment_id=segment_id,
        send_invite=send_invite,
    )
    body = {
        "id": sid,
        "carrierOrder": [
            {
                "id": carrier_order_id,
                "_operation": 1,
                "drivers": [driver_entry],
            }
        ],
    }
    return await api.request(
        tenant_slug,
        "PUT",
        f"/shipments/{shipment_id}",
        params={"fullResponse": "true"},
        json_body=body,
    )


async def replace_driver_on_shipment(
    tenant_slug: str,
    shipment_id: Any,
    *,
    carrier_order_id: int,
    contact_id: int,
    assignment_row_ids: list[str],
    segment_id: str | None = None,
    send_invite: bool = False,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """PUT /shipments/{id} — remove existing driver rows then attach new contact."""
    api = client or TurvoApiClient()
    sid = int(shipment_id) if str(shipment_id).isdigit() else shipment_id
    drivers: list[dict[str, Any]] = [
        {"driverAssignmentId": int(row_id), "_operation": 2}
        for row_id in assignment_row_ids
    ]
    drivers.append(
        _driver_add_entry(
            contact_id,
            segment_id=segment_id,
            send_invite=send_invite,
        )
    )
    body = {
        "id": sid,
        "carrierOrder": [
            {
                "id": carrier_order_id,
                "_operation": 1,
                "drivers": drivers,
            }
        ],
    }
    return await api.request(
        tenant_slug,
        "PUT",
        f"/shipments/{shipment_id}",
        params={"fullResponse": "true"},
        json_body=body,
    )


_DEFAULT_STOP_TIMEZONE = "America/Los_Angeles"


def _resolve_stop_timezone(stop: dict[str, Any], appointment: dict[str, Any]) -> str:
    nested = stop.get("location") or {}
    return (
        str(stop.get("timezone") or stop.get("timeZone") or "").strip()
        or str(appointment.get("timezone") or appointment.get("timeZone") or "").strip()
        or str(nested.get("timezone") or nested.get("timeZone") or "").strip()
        or _DEFAULT_STOP_TIMEZONE
    )


def _local_start_time_to_utc_iso(start_time: str, tz_name: str) -> str:
    from zoneinfo import ZoneInfo

    local_dt = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
    local_dt = local_dt.replace(tzinfo=ZoneInfo(tz_name))
    return local_dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_global_route_stop_by_name(
    payload: dict[str, Any],
    stop_name: str,
) -> dict[str, Any] | None:
    target = str(stop_name or "").strip()
    if not target:
        return None
    for stop in active_route_stops(global_route_stops_from_payload(payload)):
        if str(stop.get("name") or "").strip() == target:
            return stop
    return None


async def update_stop_appointment_time(
    tenant_slug: str,
    shipment_id: Any,
    *,
    stop_name: str,
    start_time: str,
    shipment_payload: dict[str, Any] | None = None,
    client: Optional[TurvoApiClient] = None,
) -> dict[str, Any]:
    """PUT delivery stop ``appointment.date`` on Turvo Public API ``globalRoute``."""
    slug = (tenant_slug or "").strip()
    sid = str(shipment_id or "").strip()
    name = str(stop_name or "").strip()
    wall_time = str(start_time or "").strip()
    if not slug or not sid or not name or not wall_time:
        raise ValueError("tenant_slug, shipment_id, stop_name, and start_time are required")

    payload = shipment_payload if isinstance(shipment_payload, dict) else None
    if payload is None:
        payload = await get_shipment(slug, sid, client=client)

    stop = _find_global_route_stop_by_name(payload, name)
    if stop is None:
        return {
            "ok": False,
            "error": "stop_not_found",
            "stop_name": name,
            "shipment_id": sid,
        }

    route_id = stop.get("id")
    if route_id is None:
        return {
            "ok": False,
            "error": "missing_route_stop_id",
            "stop_name": name,
            "shipment_id": sid,
        }

    appointment = stop.get("appointment") if isinstance(stop.get("appointment"), dict) else {}
    tz_name = _resolve_stop_timezone(stop, appointment)
    new_start_utc = _local_start_time_to_utc_iso(wall_time, tz_name)
    current_date = str(appointment.get("date") or "").strip()
    if current_date == new_start_utc:
        return {
            "ok": True,
            "updated": False,
            "stop_name": name,
            "start_time": wall_time,
            "appointment_date_utc": new_start_utc,
            "timezone": tz_name,
        }

    sid_int = int(sid) if sid.isdigit() else sid
    body = {
        "id": sid_int,
        "globalRoute": [
            {
                "_operation": 1,
                "id": route_id,
                "name": stop.get("name") or name,
                "appointment": {
                    "date": new_start_utc,
                    "timeZone": tz_name,
                    "hasTime": True,
                },
            }
        ],
    }
    api = client or TurvoApiClient()
    response = await api.request(
        slug,
        "PUT",
        f"/shipments/{sid}",
        params={"fullResponse": "true"},
        json_body=body,
    )
    success = isinstance(response, dict) and (
        response.get("respMsg") == "SUCCESS_UPDATE" or response.get("Status") == "SUCCESS"
    )
    return {
        "ok": bool(success),
        "updated": bool(success),
        "stop_name": name,
        "start_time": wall_time,
        "appointment_date_utc": new_start_utc,
        "timezone": tz_name,
        "payload": body,
        "response": response,
        "error": None if success else str((response or {}).get("respMsg") or "turvo_update_failed"),
    }
