"""Pure helpers for appointment scheduling Turvo webhook ingress (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.appointment_scheduling.constants import (
    PICKUP_STOP_TYPE_KEY,
    SHIPMENT_UPDATE_EVENT_NAME,
    TENDER_ACCEPTED_STATUS_VALUES,
    TURVO_SYSTEM_BOT_NAMES,
)
from app.domain.appointment_scheduling.scheduling_reference import (
    is_diamond_scheduling_reference,
)
from app.domain.shipment_route_locations import active_route_stops
from app.integrations.turvo.shipments import global_route_stops_from_payload
from app.integrations.turvo.webhook_mapping import extract_shipment_and_load_ids


@dataclass(frozen=True)
class ParsedShipmentUpdateWebhook:
    event_name: str
    shipment_id: str
    load_id: str | None
    tender_accepted: bool


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def normalize_tender_accepted_status(raw: Any) -> str | None:
    value = _clean(raw)
    if not value:
        return None
    return value.lower().replace(" ", "").replace("-", "")


def extract_tender_status_from_webhook(body: dict[str, Any]) -> str | None:
    event_payload = body.get("eventPayload")
    if not isinstance(event_payload, dict):
        return None
    status = event_payload.get("status")
    if not isinstance(status, dict):
        return None
    code = status.get("code")
    if isinstance(code, dict):
        for key in ("value", "key"):
            normalized = normalize_tender_accepted_status(code.get(key))
            if normalized in {s.replace("-", "") for s in TENDER_ACCEPTED_STATUS_VALUES}:
                return normalized
    return normalize_tender_accepted_status(status.get("value"))


def parse_shipment_update_webhook(body: dict[str, Any]) -> ParsedShipmentUpdateWebhook | None:
    """Return parsed SHIPMENT_UPDATE fields, or None when event is not scheduling-relevant."""
    event_name = _clean(body.get("eventName"))
    if event_name != SHIPMENT_UPDATE_EVENT_NAME:
        return None

    shipment_id, load_id = extract_shipment_and_load_ids(body)
    sid = _clean(shipment_id)
    if not sid:
        return None

    status = extract_tender_status_from_webhook(body)
    return ParsedShipmentUpdateWebhook(
        event_name=event_name,
        shipment_id=sid,
        load_id=_clean(load_id),
        tender_accepted=status in {s.replace("-", "") for s in TENDER_ACCEPTED_STATUS_VALUES},
    )


def get_ship_locations_from_activity_json(activity_json: dict[str, Any]) -> list[dict[str, Any]]:
    data = activity_json.get("data") or []
    if not isinstance(data, list):
        return []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        context = entry.get("context_snapshot") or {}
        if not isinstance(context, dict):
            continue
        global_route = context.get("global_route") or {}
        if not isinstance(global_route, dict):
            continue
        ship_locations = global_route.get("ship_locations") or []
        if isinstance(ship_locations, list) and ship_locations:
            return [loc for loc in ship_locations if isinstance(loc, dict)]
    return []


def ship_location_count(activity_json: dict[str, Any]) -> int:
    return len(get_ship_locations_from_activity_json(activity_json))


def is_multi_stop(activity_json: dict[str, Any]) -> bool:
    return ship_location_count(activity_json) > 2


def is_multi_stop_shipment(payload: dict[str, Any]) -> bool:
    """True when shipment ``globalRoute`` has more than pickup + one delivery."""
    return len(active_route_stops(global_route_stops_from_payload(payload))) > 2


def pickup_changed_in_activity_delta(activity_json: dict[str, Any]) -> bool:
    """True when latest non-bot activity shows pickup appointment date change."""
    data = activity_json.get("data") or []
    if not isinstance(data, list):
        return False

    latest = None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        created_by = (entry.get("record_metadata") or {}).get("created_by") or {}
        if not isinstance(created_by, dict):
            continue
        creator_name = _clean(created_by.get("name")) or ""
        if creator_name in TURVO_SYSTEM_BOT_NAMES:
            continue
        latest = entry
        break
    if latest is None:
        return False

    delta = ((latest.get("context_snapshot") or {}).get("delta") or {})
    if not isinstance(delta, dict):
        return False

    prev_diff = (delta.get("prev_diff_context") or {}).get("global_route") or {}
    if not isinstance(prev_diff, dict):
        return False
    ship_locations = prev_diff.get("ship_locations") or []
    if not isinstance(ship_locations, list):
        return False

    for loc in ship_locations:
        if not isinstance(loc, dict):
            continue
        type_info = loc.get("type") or {}
        if not isinstance(type_info, dict):
            continue
        if _clean(type_info.get("key")) != PICKUP_STOP_TYPE_KEY:
            continue

        prev_appt = ((loc.get("appointment") or {}).get("date"))
        final_ship_locations = (
            (delta.get("final_diff_context") or {})
            .get("global_route", {})
            .get("ship_locations", [])
        )
        final_loc = next(
            (
                item
                for item in final_ship_locations
                if isinstance(item, dict)
                and _clean((item.get("type") or {}).get("key")) == PICKUP_STOP_TYPE_KEY
            ),
            {},
        )
        final_appt = ((final_loc.get("appointment") or {}).get("date"))
        if prev_appt and final_appt and prev_appt != final_appt:
            return True
    return False


def _external_ids_from_customer_order(order: dict[str, Any]) -> list[dict[str, Any]]:
    raw = order.get("externalIds") or order.get("external_ids") or []
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    return []


def reference_number_from_turvo_shipment(payload: dict[str, Any]) -> str | None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else payload
    if not isinstance(details, dict):
        return None

    orders = details.get("customerOrder") or details.get("customer_order") or []
    if not isinstance(orders, list):
        return None

    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        for external in _external_ids_from_customer_order(order):
            value = _clean(external.get("idValue") or external.get("id_value") or external.get("value"))
            if value:
                return value
    return None


def load_id_from_turvo_shipment(payload: dict[str, Any]) -> str | None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else payload
    if not isinstance(details, dict):
        return None
    for key in ("customId", "custom_id"):
        value = _clean(details.get(key))
        if value:
            return value
    return None


def customer_name_from_turvo_shipment(payload: dict[str, Any]) -> str | None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else payload
    if not isinstance(details, dict):
        return None
    orders = details.get("customerOrder") or details.get("customer_order") or []
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        customer = order.get("customer") or {}
        if isinstance(customer, dict):
            name = _clean(customer.get("name"))
            if name:
                return name
    return None


def customer_id_from_turvo_shipment(payload: dict[str, Any]) -> str | None:
    details = payload.get("details") if isinstance(payload.get("details"), dict) else payload
    if not isinstance(details, dict):
        return None
    orders = details.get("customerOrder") or details.get("customer_order") or []
    if not isinstance(orders, list):
        return None
    for order in orders:
        if not isinstance(order, dict) or order.get("deleted"):
            continue
        customer = order.get("customer") or {}
        if isinstance(customer, dict):
            cid = _clean(customer.get("id"))
            if cid:
                return cid
    return None


__all__ = [
    "ParsedShipmentUpdateWebhook",
    "customer_id_from_turvo_shipment",
    "customer_name_from_turvo_shipment",
    "is_diamond_scheduling_reference",
    "is_multi_stop",
    "is_multi_stop_shipment",
    "load_id_from_turvo_shipment",
    "parse_shipment_update_webhook",
    "pickup_changed_in_activity_delta",
    "reference_number_from_turvo_shipment",
    "ship_location_count",
]
