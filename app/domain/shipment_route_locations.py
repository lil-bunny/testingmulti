"""Vendor-agnostic route stop → location lookup keys for shipment FK linking."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


class ShipmentLocationLinkError(ValueError):
    """Raised when pickup/delivery locations cannot be resolved or linked."""


@dataclass(frozen=True)
class LocationLookup:
    city: str
    state_code: str
    country: str


@dataclass(frozen=True)
class RouteEndpoints:
    pickup: LocationLookup
    delivery: LocationLookup


StructuredDeliveryAddress = dict[str, Any]
DeliveryAddressFromStop = Callable[[dict[str, Any]], StructuredDeliveryAddress | None]


def _is_deleted(stop: dict[str, Any]) -> bool:
    return bool(stop.get("deleted"))


def _address_from_stop(stop: dict[str, Any]) -> dict[str, Any]:
    address = stop.get("address")
    return address if isinstance(address, dict) else {}


def _location_lookup_from_address(address: dict[str, Any]) -> LocationLookup:
    city = str(address.get("city") or "").strip()
    state_code = str(address.get("state") or "").strip()
    country = str(address.get("countryCode") or address.get("country") or "US").strip()
    if not city or not state_code:
        raise ShipmentLocationLinkError(
            f"route stop address missing city or state: city={city!r} state={state_code!r}"
        )
    if not country:
        country = "US"
    return LocationLookup(city=city, state_code=state_code, country=country)


def active_route_stops(stops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Non-deleted route stops in route order."""
    return [s for s in stops if isinstance(s, dict) and not _is_deleted(s)]


def last_active_route_stop(stops: list[dict[str, Any]]) -> dict[str, Any]:
    """Last non-deleted stop (delivery endpoint for structured address builders)."""
    active = active_route_stops(stops)
    if not active:
        raise ShipmentLocationLinkError("no non-deleted route stops")
    return active[-1]


def endpoints_from_route_stops(stops: list[dict[str, Any]]) -> RouteEndpoints:
    """First and last non-deleted stops → pickup and delivery lookup keys."""
    active = active_route_stops(stops)
    if not active:
        raise ShipmentLocationLinkError("no non-deleted route stops")
    pickup = _location_lookup_from_address(_address_from_stop(active[0]))
    delivery = _location_lookup_from_address(_address_from_stop(active[-1]))
    return RouteEndpoints(pickup=pickup, delivery=delivery)
