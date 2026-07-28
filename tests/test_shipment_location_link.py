"""Tests for shipment location FK linking from route stops."""

from __future__ import annotations

import types
from unittest.mock import MagicMock

import pytest

from app.domain.shipment_route_locations import (
    LocationLookup,
    ShipmentLocationLinkError,
    active_route_stops,
    endpoints_from_route_stops,
    last_active_route_stop,
)
from app.integrations.turvo.shipments import (
    delivery_address_from_global_route_stop,
    global_route_stops_from_payload,
    location_insert_row_from_route_stop,
    postal_from_customer_order_route,
)
from app.services.shipment_location_link_service import (
    ShipmentLocationLinkResult,
    ShipmentLocationLinkService,
)
from app.workflows.nodes import turvo as turvo_nodes


def _stop(
    *,
    city: str,
    state: str,
    country_code: str = "US",
    deleted: bool = False,
    zip_code: str | None = None,
) -> dict:
    address: dict = {
        "city": city,
        "state": state,
        "countryCode": country_code,
    }
    if zip_code:
        address["zip"] = zip_code
    return {
        "deleted": deleted,
        "address": address,
    }


THREE_STOP_ROUTE = [
    _stop(city="Ripon", state="CA"),
    _stop(city="SPARKS", state="NV"),
    _stop(city="RENO", state="NV"),
]


RENO_STOP_NO_ZIP = {
    "id": 5797256,
    "deleted": False,
    "name": "COSTCO #25 CNC",
    "location": {"id": 647909, "name": "COSTCO #25 CNC"},
    "address": {
        "line1": "2200 HARVARD WAY",
        "city": "RENO",
        "state": "NV",
        "countryCode": "US",
    },
}

SHIPMENT_DETAILS_CO_ZIP = {
    "customerOrder": [
        {
            "deleted": False,
            "route": [
                {
                    "deleted": False,
                    "globalShipLocationId": 5797256,
                    "address": {
                        "city": "RENO",
                        "state": "NV",
                        "zip": "89502",
                    },
                }
            ],
        }
    ],
}


def _full_delivery_stop() -> dict:
    return {
        "deleted": False,
        "name": "COSTCO #25 CNC",
        "location": {"id": 647909, "name": "COSTCO #25 CNC"},
        "address": {
            "line1": "2200 HARVARD WAY",
            "line2": "",
            "city": "RENO",
            "state": "NV",
            "zip": "89502",
            "country": "US",
        },
    }


class TestActiveRouteStops:
    def test_last_active_route_stop(self) -> None:
        stop = last_active_route_stop(THREE_STOP_ROUTE)
        assert stop["address"]["city"] == "RENO"

    def test_active_route_stops_filters_deleted(self) -> None:
        route = [
            _stop(city="A", state="TX", deleted=True),
            _stop(city="B", state="TX"),
        ]
        assert len(active_route_stops(route)) == 1


class TestDeliveryAddressFromGlobalRouteStop:
    def test_maps_full_stop(self) -> None:
        out = delivery_address_from_global_route_stop(_full_delivery_stop())
        assert out is not None
        assert out["name"] == "COSTCO #25 CNC"
        assert out["address1"] == "2200 HARVARD WAY"
        assert out["city"] == "RENO"
        assert out["state"] == "NV"
        assert out["postal_code"] == "89502"
        assert out["country"] == "US"

    def test_returns_none_without_city_or_state(self) -> None:
        assert delivery_address_from_global_route_stop({"address": {"state": "NV"}}) is None

    def test_stop_without_zip_has_empty_postal(self) -> None:
        out = delivery_address_from_global_route_stop(RENO_STOP_NO_ZIP)
        assert out is not None
        assert out["postal_code"] == ""


class TestPostalFromCustomerOrderRoute:
    def test_matches_global_route_stop_id(self) -> None:
        postal = postal_from_customer_order_route(
            SHIPMENT_DETAILS_CO_ZIP,
            RENO_STOP_NO_ZIP,
        )
        assert postal == "89502"

    def test_no_match_returns_none(self) -> None:
        stop = {**RENO_STOP_NO_ZIP, "id": 999}
        assert (
            postal_from_customer_order_route(SHIPMENT_DETAILS_CO_ZIP, stop) is None
        )


class TestEndpointsFromRouteStops:
    def test_three_stops_first_and_last(self) -> None:
        out = endpoints_from_route_stops(THREE_STOP_ROUTE)
        assert out.pickup == LocationLookup(city="Ripon", state_code="CA", country="US")
        assert out.delivery == LocationLookup(city="RENO", state_code="NV", country="US")

    def test_filters_deleted(self) -> None:
        route = [
            _stop(city="A", state="TX", deleted=True),
            _stop(city="B", state="TX"),
            _stop(city="C", state="TX"),
        ]
        out = endpoints_from_route_stops(route)
        assert out.pickup.city == "B"
        assert out.delivery.city == "C"

    def test_empty_raises(self) -> None:
        with pytest.raises(ShipmentLocationLinkError, match="no non-deleted"):
            endpoints_from_route_stops([])

    def test_missing_city_raises(self) -> None:
        with pytest.raises(ShipmentLocationLinkError, match="missing city or state"):
            endpoints_from_route_stops([{"address": {"state": "CA"}}])


class TestLocationInsertRowFromRouteStop:
    def test_maps_zip_on_stop(self) -> None:
        stop = _stop(city="Hanover", state="MD", zip_code="21076")
        row = location_insert_row_from_route_stop(stop)
        assert row is not None
        assert row["city"] == "Hanover"
        assert row["state_code"] == "MD"
        assert row["postal_code"] == "21076"
        assert row["country"] == "US"

    def test_uses_customer_order_zip_when_global_route_omits_it(self) -> None:
        row = location_insert_row_from_route_stop(
            RENO_STOP_NO_ZIP,
            SHIPMENT_DETAILS_CO_ZIP,
        )
        assert row is not None
        assert row["postal_code"] == "89502"
        assert row["city"] == "RENO"
        assert row["state_code"] == "NV"

    def test_missing_city_returns_none(self) -> None:
        assert location_insert_row_from_route_stop({"address": {"state": "MD"}}) is None


class TestGlobalRouteStopsFromPayload:
    def test_reads_details_global_route(self) -> None:
        payload = {"details": {"globalRoute": THREE_STOP_ROUTE}}
        assert len(global_route_stops_from_payload(payload)) == 3

    def test_missing_route_returns_empty(self) -> None:
        assert global_route_stops_from_payload({}) == []
        assert global_route_stops_from_payload({"details": {}}) == []


class TestShipmentLocationLinkService:
    def test_success(self) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        result = svc.link_from_route_stops(
            THREE_STOP_ROUTE,
            shipments_row_id="ship-row-1",
        )
        assert isinstance(result, ShipmentLocationLinkResult)
        assert result.pickup_location_id == "pickup-uuid"
        assert result.delivery_location_id == "delivery-uuid"
        shipments.update_location_ids_tx.assert_called_once_with(
            shipment_row_id="ship-row-1",
            pickup_location_id="pickup-uuid",
            delivery_location_id="delivery-uuid",
            delivery_address=None,
        )
        assert result.delivery_address is None

    def test_delivery_address_builder_persisted(self) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        route = [_stop(city="Ripon", state="CA"), _full_delivery_stop()]
        result = svc.link_from_route_stops(
            route,
            shipments_row_id="ship-row-1",
            delivery_address_builder=delivery_address_from_global_route_stop,
        )
        assert result.delivery_address is not None
        assert result.delivery_address["city"] == "RENO"
        shipments.update_location_ids_tx.assert_called_once()
        call_kw = shipments.update_location_ids_tx.call_args.kwargs
        assert call_kw["delivery_address"]["address1"] == "2200 HARVARD WAY"

    def test_fills_postal_from_customer_order_when_global_route_omits_zip(
        self,
    ) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        route = [_stop(city="Ripon", state="CA"), RENO_STOP_NO_ZIP]
        result = svc.link_from_route_stops(
            route,
            shipments_row_id="ship-row-1",
            delivery_address_builder=delivery_address_from_global_route_stop,
            shipment_details=SHIPMENT_DETAILS_CO_ZIP,
        )
        assert result.delivery_address is not None
        assert result.delivery_address["postal_code"] == "89502"
        locations.get_postal_code_by_id.assert_not_called()

    def test_fills_postal_from_locations_when_customer_order_missing(
        self,
    ) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        locations.get_postal_code_by_id.return_value = "89502"
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        route = [_stop(city="Ripon", state="CA"), RENO_STOP_NO_ZIP]
        result = svc.link_from_route_stops(
            route,
            shipments_row_id="ship-row-1",
            delivery_address_builder=delivery_address_from_global_route_stop,
            shipment_details=None,
        )
        assert result.delivery_address is not None
        assert result.delivery_address["postal_code"] == "89502"
        locations.get_postal_code_by_id.assert_called_once_with("delivery-uuid")

    def test_fills_postal_from_pgeocode_last_resort(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        locations.get_postal_code_by_id.return_value = None
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        monkeypatch.setattr(
            "app.services.shipment_location_link_service.lookup_postal",
            lambda country, city, state: "89502" if city == "RENO" else None,
        )
        route = [_stop(city="Ripon", state="CA"), RENO_STOP_NO_ZIP]
        result = svc.link_from_route_stops(
            route,
            shipments_row_id="ship-row-1",
            delivery_address_builder=delivery_address_from_global_route_stop,
            shipment_details=None,
        )
        assert result.delivery_address is not None
        assert result.delivery_address["postal_code"] == "89502"

    def test_missing_row_id_raises(self) -> None:
        svc = ShipmentLocationLinkService(
            locations_repository=MagicMock(),
            shipments_repository=MagicMock(),
        )
        with pytest.raises(ShipmentLocationLinkError, match="missing shipments_row_id"):
            svc.link_from_route_stops(THREE_STOP_ROUTE, shipments_row_id=None)

    def test_link_from_turvo_shipment_payload_delegates_to_route_stops(self) -> None:
        svc = ShipmentLocationLinkService(
            locations_repository=MagicMock(),
            shipments_repository=MagicMock(),
        )
        turvo_payload = {"details": {"globalRoute": THREE_STOP_ROUTE}}
        svc.link_from_route_stops = MagicMock(
            return_value=ShipmentLocationLinkResult(
                pickup_location_id="p-id",
                delivery_location_id="d-id",
                pickup=LocationLookup(city="Ripon", state_code="CA", country="US"),
                delivery=LocationLookup(city="RENO", state_code="NV", country="US"),
            )
        )
        result = svc.link_from_turvo_shipment_payload(
            turvo_payload,
            shipments_row_id="ship-row-1",
        )
        assert result.pickup_location_id == "p-id"
        svc.link_from_route_stops.assert_called_once()
        call_kw = svc.link_from_route_stops.call_args.kwargs
        assert call_kw["shipments_row_id"] == "ship-row-1"
        assert call_kw["delivery_address_builder"] is delivery_address_from_global_route_stop
        assert call_kw["shipment_details"] == turvo_payload["details"]

    def test_try_link_from_turvo_returns_none_on_link_error(self) -> None:
        svc = ShipmentLocationLinkService(
            locations_repository=MagicMock(),
            shipments_repository=MagicMock(),
        )
        svc.link_from_turvo_shipment_payload = MagicMock(
            side_effect=ShipmentLocationLinkError("missing shipments_row_id")
        )
        assert (
            svc.try_link_from_turvo_shipment_payload(
                {"details": {"globalRoute": THREE_STOP_ROUTE}},
                shipments_row_id="ship-row-1",
            )
            is None
        )

    def test_location_not_found_raises_when_insert_fails(self) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.return_value = None
        locations.insert_location_tx.return_value = None
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=MagicMock(),
        )
        with pytest.raises(ShipmentLocationLinkError, match="location not found"):
            svc.link_from_route_stops(
                THREE_STOP_ROUTE,
                shipments_row_id="ship-row-1",
            )

    def test_creates_location_on_miss_from_route_stop(self) -> None:
        locations = MagicMock()
        locations.find_id_by_city_state_country_tx.side_effect = [None, None]
        locations.insert_location_tx.side_effect = [
            "pickup-uuid",
            "delivery-uuid",
        ]
        shipments = MagicMock()
        svc = ShipmentLocationLinkService(
            locations_repository=locations,
            shipments_repository=shipments,
        )
        route = [
            _stop(city="Hanover", state="MD", zip_code="21076"),
            _stop(city="RENO", state="NV", zip_code="89502"),
        ]
        result = svc.link_from_route_stops(
            route,
            shipments_row_id="ship-row-1",
        )
        assert result.pickup_location_id == "pickup-uuid"
        assert result.delivery_location_id == "delivery-uuid"
        assert locations.insert_location_tx.call_count == 2


class TestLinkShipmentLocationsNode:
    def test_propagates_service_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = types.SimpleNamespace(
            data={
                "shipment": {"details": {"globalRoute": THREE_STOP_ROUTE}},
                "shipments_row_id": "ship-row-1",
            }
        )
        mock_svc = MagicMock()
        mock_svc.link_from_turvo_shipment_payload.side_effect = ShipmentLocationLinkError(
            "location not found"
        )
        monkeypatch.setattr(
            turvo_nodes,
            "ShipmentLocationLinkService",
            lambda: mock_svc,
        )
        with pytest.raises(ShipmentLocationLinkError, match="location not found"):
            turvo_nodes.link_shipment_locations(state)

    def test_sets_state_on_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        state = types.SimpleNamespace(
            data={
                "shipment": {"details": {"globalRoute": THREE_STOP_ROUTE}},
                "shipments_row_id": "ship-row-1",
            }
        )
        mock_svc = MagicMock()
        mock_svc.link_from_turvo_shipment_payload.return_value = ShipmentLocationLinkResult(
            pickup_location_id="p-id",
            delivery_location_id="d-id",
            pickup=LocationLookup(city="Ripon", state_code="CA", country="US"),
            delivery=LocationLookup(city="RENO", state_code="NV", country="US"),
        )
        monkeypatch.setattr(
            turvo_nodes,
            "ShipmentLocationLinkService",
            lambda: mock_svc,
        )
        turvo_nodes.link_shipment_locations(state)
        assert state.data["shipment_location_link"]["success"] is True
        assert state.data["shipment_location_link"]["pickup_location_id"] == "p-id"
        mock_svc.link_from_turvo_shipment_payload.assert_called_once()
        call_args = mock_svc.link_from_turvo_shipment_payload.call_args
        assert call_args.args[0] == {"details": {"globalRoute": THREE_STOP_ROUTE}}
        assert call_args.kwargs["shipments_row_id"] == "ship-row-1"
