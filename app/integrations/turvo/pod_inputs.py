"""Extract Turvo ``get_shipment`` payloads into PoD-scoring inputs.

Pure transform of ``state.data["shipment"]`` — no new Turvo call. Kept separate
from ``app.integrations.turvo.shipments`` (driver/appointment parsing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.shipment_route_locations import active_route_stops
from app.integrations.turvo.shipments import global_route_stops_from_payload

StopType = Literal["pickup", "delivery"]

_STOP_TYPE_BY_KEY: dict[str, StopType] = {"1500": "pickup", "1501": "delivery"}
_STOP_TYPE_BY_VALUE: dict[str, StopType] = {"pickup": "pickup", "delivery": "delivery"}
_PALLET_COUNT_PATTERN = re.compile(r"Pallets:\s*(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class TurvoPurchaseOrder:
    """One stop-scoped PO from ``globalRoute[].poNumbers[]`` (not de-duped across stops)."""

    po_number: str
    stop_type: StopType


@dataclass(frozen=True)
class TurvoStop:
    """One Turvo ``globalRoute`` pickup or delivery stop, reduced for PoD scoring."""

    name: str
    address: str
    po_numbers: list[str] = field(default_factory=list)
    time_zone: str | None = None


@dataclass(frozen=True)
class TurvoShipmentPodInputs:
    """Turvo-side inputs for ``score_pod`` (stops, POs, dates, pallet qty)."""

    is_single_stop: bool
    pickup: TurvoStop
    delivery: TurvoStop
    purchase_orders: list[TurvoPurchaseOrder]
    pickup_date: str | None
    delivery_date: str | None
    ordered_pallet_qty: int | None
    custom_id: str | None


_EMPTY_STOP = TurvoStop(name="", address="", po_numbers=[], time_zone=None)


def _clean_str(val: Any) -> str | None:
    s = str(val or "").strip()
    return s or None


def _stop_type(stop: dict[str, Any]) -> StopType | None:
    """Classify a ``globalRoute`` stop as pickup/delivery by ``stopType.key`` (fallback ``value``)."""
    stop_type = stop.get("stopType")
    if not isinstance(stop_type, dict):
        return None
    key = str(stop_type.get("key") or "").strip()
    if key in _STOP_TYPE_BY_KEY:
        return _STOP_TYPE_BY_KEY[key]
    value = str(stop_type.get("value") or "").strip().lower()
    return _STOP_TYPE_BY_VALUE.get(value)


def _address_line(address: dict[str, Any]) -> str:
    if not isinstance(address, dict):
        return ""
    parts = [
        str(address.get("line1") or "").strip(),
        str(address.get("city") or "").strip(),
        str(address.get("state") or "").strip(),
        str(address.get("countryCode") or address.get("country") or "").strip(),
    ]
    return ", ".join(p for p in parts if p)


def _po_numbers_from_stop(stop: dict[str, Any]) -> list[str]:
    raw = stop.get("poNumbers")
    if not isinstance(raw, list):
        return []
    return [str(v).strip() for v in raw if str(v or "").strip()]


def _turvo_stop_from_global_route(stop: dict[str, Any]) -> TurvoStop:
    address = stop.get("address")
    return TurvoStop(
        name=str(stop.get("name") or "").strip(),
        address=_address_line(address if isinstance(address, dict) else {}),
        po_numbers=_po_numbers_from_stop(stop),
        time_zone=_clean_str(stop.get("timezone") or stop.get("timeZone")),
    )


def _purchase_orders_from_stops(pickup: TurvoStop, delivery: TurvoStop) -> list[TurvoPurchaseOrder]:
    """Flatten both stops' ``poNumbers[]`` into independent, stop-tagged POs (no de-dup)."""
    pickup_pos = [TurvoPurchaseOrder(po_number=po, stop_type="pickup") for po in pickup.po_numbers]
    delivery_pos = [TurvoPurchaseOrder(po_number=po, stop_type="delivery") for po in delivery.po_numbers]
    return pickup_pos + delivery_pos


def _ordered_pallet_qty_from_stop(stop: dict[str, Any]) -> int | None:
    """Parse "Pallets: N | ..." from a stop's free-text ``notes`` field."""
    match = _PALLET_COUNT_PATTERN.search(str(stop.get("notes") or ""))
    return int(match.group(1)) if match else None


def extract_pod_inputs_from_shipment(payload: dict[str, Any]) -> TurvoShipmentPodInputs:
    """
    Extract PoD-scoring inputs from a Turvo ``get_shipment`` payload.

    Sets ``is_single_stop=False`` when pickup/delivery stop counts are not
    exactly one each so ``pod_scoring`` can skip multi-stop shipments.
    """
    stops = active_route_stops(global_route_stops_from_payload(payload))
    pickup_stops = [s for s in stops if _stop_type(s) == "pickup"]
    delivery_stops = [s for s in stops if _stop_type(s) == "delivery"]

    pickup = _turvo_stop_from_global_route(pickup_stops[0]) if pickup_stops else _EMPTY_STOP
    delivery = _turvo_stop_from_global_route(delivery_stops[0]) if delivery_stops else _EMPTY_STOP

    details = payload.get("details") if isinstance(payload, dict) else None
    details = details if isinstance(details, dict) else {}
    start_date = details.get("startDate")
    end_date = details.get("endDate")

    return TurvoShipmentPodInputs(
        is_single_stop=len(pickup_stops) == 1 and len(delivery_stops) == 1,
        pickup=pickup,
        delivery=delivery,
        purchase_orders=_purchase_orders_from_stops(pickup, delivery),
        pickup_date=_clean_str(start_date.get("date")) if isinstance(start_date, dict) else None,
        delivery_date=_clean_str(end_date.get("date")) if isinstance(end_date, dict) else None,
        ordered_pallet_qty=_ordered_pallet_qty_from_stop(pickup_stops[0]) if pickup_stops else None,
        custom_id=_clean_str(details.get("customId")),
    )
