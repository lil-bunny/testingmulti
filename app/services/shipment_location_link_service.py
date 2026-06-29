"""Link ``shipments`` pickup/delivery FKs from route stop addresses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.shipment_route_locations import (
    DeliveryAddressFromStop,
    LocationLookup,
    ShipmentLocationLinkError,
    active_route_stops,
    endpoints_from_route_stops,
    last_active_route_stop,
)
from app.integrations.pgeocode.state_lookup import lookup_postal
from app.integrations.turvo.shipments import (
    location_insert_row_from_route_stop,
    postal_from_customer_order_route,
)
from app.repositories.locations_repository import LocationsRepository
from app.repositories.shipments_repository import ShipmentsRepository

logger = get_logger(__name__)


@dataclass(frozen=True)
class ShipmentLocationLinkResult:
    pickup_location_id: str
    delivery_location_id: str
    pickup: LocationLookup
    delivery: LocationLookup
    delivery_address: dict[str, Any] | None = None


class ShipmentLocationLinkService:
    def __init__(
        self,
        *,
        locations_repository: LocationsRepository | None = None,
        shipments_repository: ShipmentsRepository | None = None,
    ) -> None:
        self._locations = locations_repository
        self._shipments = shipments_repository

    @staticmethod
    def _clean_row_id(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _resolve_or_create_location_id(
        locations: LocationsRepository,
        lookup: LocationLookup,
        route_stop: dict[str, Any],
        shipment_details: dict[str, Any] | None,
    ) -> str:
        try:
            location_id = locations.find_id_by_city_state_country_tx(
                city=lookup.city,
                state_code=lookup.state_code,
                country=lookup.country,
            )
        except Exception:
            logger.exception(
                "location lookup failed city=%s state_code=%s country=%s",
                lookup.city,
                lookup.state_code,
                lookup.country,
            )
            raise
        if location_id:
            return location_id

        insert_row = location_insert_row_from_route_stop(
            route_stop,
            shipment_details,
        )
        if insert_row is None:
            raise ShipmentLocationLinkError(
                "location not found and route stop lacks city/state for "
                f"city={lookup.city!r} state_code={lookup.state_code!r} "
                f"country={lookup.country!r}"
            )

        try:
            inserted_id = locations.insert_location_tx(**insert_row)
        except Exception:
            logger.exception(
                "location insert failed city=%s state_code=%s country=%s",
                lookup.city,
                lookup.state_code,
                lookup.country,
            )
            raise

        if inserted_id:
            logger.info(
                "inserted location from Turvo route stop city=%s state_code=%s country=%s postal=%s",
                insert_row["city"],
                insert_row["state_code"],
                insert_row["country"],
                insert_row.get("postal_code"),
            )
            return inserted_id

        location_id = locations.find_id_by_city_state_country_tx(
            city=lookup.city,
            state_code=lookup.state_code,
            country=lookup.country,
        )
        if location_id:
            return location_id

        raise ShipmentLocationLinkError(
            "location not found for "
            f"city={lookup.city!r} state_code={lookup.state_code!r} "
            f"country={lookup.country!r}"
        )

    @staticmethod
    def _postal_code_empty(delivery_address: dict[str, Any]) -> bool:
        return not str(delivery_address.get("postal_code") or "").strip()

    @staticmethod
    def _resolve_missing_postal_code(
        locations: LocationsRepository,
        delivery_address: dict[str, Any],
        *,
        last_stop: dict[str, Any],
        delivery_location_id: str,
        shipment_details: dict[str, Any] | None,
    ) -> None:
        if not ShipmentLocationLinkService._postal_code_empty(delivery_address):
            return

        if isinstance(shipment_details, dict):
            postal = postal_from_customer_order_route(shipment_details, last_stop)
            if postal:
                delivery_address["postal_code"] = postal
                return

        postal = locations.get_postal_code_by_id(delivery_location_id)
        if postal:
            delivery_address["postal_code"] = postal
            return

        postal = lookup_postal(
            delivery_address.get("country"),
            delivery_address.get("city"),
            delivery_address.get("state"),
        )
        if postal:
            delivery_address["postal_code"] = postal

    def _link_impl(
        self,
        locations: LocationsRepository,
        shipments: ShipmentsRepository,
        stops: list[dict[str, Any]],
        *,
        row_id: str,
        delivery_address_builder: DeliveryAddressFromStop | None,
        shipment_details: dict[str, Any] | None,
    ) -> ShipmentLocationLinkResult:
        active = active_route_stops(stops)
        endpoints = endpoints_from_route_stops(stops)
        pickup_id = self._resolve_or_create_location_id(
            locations,
            endpoints.pickup,
            active[0],
            shipment_details,
        )
        delivery_id = self._resolve_or_create_location_id(
            locations,
            endpoints.delivery,
            active[-1],
            shipment_details,
        )

        last_stop = last_active_route_stop(stops)
        delivery_address: dict[str, Any] | None = None
        if delivery_address_builder is not None:
            try:
                delivery_address = delivery_address_builder(last_stop)
            except Exception:
                logger.exception(
                    "delivery_address builder failed shipments_row_id=%s",
                    row_id,
                )
            if delivery_address is None:
                logger.info(
                    "delivery_address not resolved shipments_row_id=%s",
                    row_id,
                )
            elif self._postal_code_empty(delivery_address):
                self._resolve_missing_postal_code(
                    locations,
                    delivery_address,
                    last_stop=last_stop,
                    delivery_location_id=delivery_id,
                    shipment_details=shipment_details,
                )

        try:
            shipments.update_location_ids_tx(
                shipment_row_id=row_id,
                pickup_location_id=pickup_id,
                delivery_location_id=delivery_id,
                delivery_address=delivery_address,
            )
        except ShipmentLocationLinkError:
            raise
        except Exception:
            logger.exception(
                "shipments location FK update failed shipments_row_id=%s",
                row_id,
            )
            raise

        return ShipmentLocationLinkResult(
            pickup_location_id=pickup_id,
            delivery_location_id=delivery_id,
            pickup=endpoints.pickup,
            delivery=endpoints.delivery,
            delivery_address=delivery_address,
        )

    def link_from_route_stops(
        self,
        stops: list[dict[str, Any]],
        *,
        shipments_row_id: str | None,
        delivery_address_builder: DeliveryAddressFromStop | None = None,
        shipment_details: dict[str, Any] | None = None,
    ) -> ShipmentLocationLinkResult:
        row_id = self._clean_row_id(shipments_row_id)
        if not row_id:
            raise ShipmentLocationLinkError("missing shipments_row_id")

        if self._locations is not None and self._shipments is not None:
            return self._link_impl(
                self._locations,
                self._shipments,
                stops,
                row_id=row_id,
                delivery_address_builder=delivery_address_builder,
                shipment_details=shipment_details,
            )

        def _run(repos: Any) -> ShipmentLocationLinkResult:
            locations = self._locations or repos.locations
            shipments = self._shipments or repos.shipments
            return self._link_impl(
                locations,
                shipments,
                stops,
                row_id=row_id,
                delivery_address_builder=delivery_address_builder,
                shipment_details=shipment_details,
            )

        return run_with_repos(_run)
