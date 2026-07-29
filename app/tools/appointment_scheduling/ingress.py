"""Pure helpers for appointment scheduling Turvo webhook ingress (no I/O)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.appointment_scheduling.constants import (
    PICKUP_STOP_TYPE_KEY,
    SHIPMENT_UPDATE_EVENT_NAME,
    TURVO_SYSTEM_BOT_NAMES,
)
from app.integrations.turvo.shipments import is_multi_stop_shipment
from app.integrations.turvo.webhook_mapping import (
    TENDER_ACCEPTED_STATUS_CODE_KEY,
    extract_shipment_and_load_ids,
    extract_status_code_key,
)


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


def parse_shipment_update_webhook(body: dict[str, Any]) -> ParsedShipmentUpdateWebhook | None:
    """Return parsed SHIPMENT_UPDATE fields, or None when event is not scheduling-relevant."""
    event_name = _clean(body.get("eventName"))
    if event_name != SHIPMENT_UPDATE_EVENT_NAME:
        return None

    shipment_id, load_id = extract_shipment_and_load_ids(body)
    sid = _clean(shipment_id)
    if not sid:
        return None

    status_key = extract_status_code_key(body)
    return ParsedShipmentUpdateWebhook(
        event_name=event_name,
        shipment_id=sid,
        load_id=_clean(load_id),
        tender_accepted=status_key == TENDER_ACCEPTED_STATUS_CODE_KEY,
    )


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
