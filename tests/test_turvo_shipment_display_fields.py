"""Unit tests for Turvo shipment display field extraction."""

from __future__ import annotations

from datetime import datetime, timezone

from app.integrations.turvo.shipments import (
    appointment_scheduling_display_fields_from_payload,
    delivery_appointment_from_payload,
    shipment_display_fields_from_payload,
)

SHIPMENT_1000324895_FIXTURE: dict = {
    "details": {
        "customerOrder": [
            {
                "deleted": False,
                "customer": {"id": 850901, "name": "DIAMOND PET FOODS"},
            }
        ],
        "carrierOrder": [
            {
                "deleted": True,
                "carrier": {"id": 848297, "name": "Old Carrier"},
            },
            {
                "deleted": False,
                "carrier": {"id": 848297, "name": "Turvo Test Carrier"},
            },
        ],
        "globalRoute": [
            {
                "deleted": False,
                "name": "Diamond Pet Foods - Ripon",
                "address": {"city": "Ripon", "state": "CA"},
                "stopType": {"value": "Pickup"},
                "timezone": "America/Los_Angeles",
                "appointment": {"date": "2026-03-30T14:00:00Z", "timeZone": "America/Los_Angeles"},
            },
            {
                "deleted": False,
                "name": "PETCO DC 810",
                "address": {"city": "CRANBURY", "state": "NJ"},
                "stopType": {"value": "Delivery"},
                "timezone": "America/New_York",
                "appointment": {
                    "date": "2026-04-01T07:01:00Z",
                    "timeZone": "America/New_York",
                },
            },
        ],
    }
}


def test_shipment_display_fields_from_payload_full_fixture() -> None:
    out = shipment_display_fields_from_payload(SHIPMENT_1000324895_FIXTURE)
    assert out.customer_name == "DIAMOND PET FOODS"
    assert out.carrier_name == "Turvo Test Carrier"
    assert out.pickup_date == datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
    assert out.pickup_timezone == "America/Los_Angeles"
    assert out.delivery_date == datetime(2026, 4, 1, 7, 1, tzinfo=timezone.utc)
    assert out.delivery_timezone == "America/New_York"


def test_appointment_scheduling_display_fields_uses_delivery_stop_as_customer_name() -> None:
    standard = shipment_display_fields_from_payload(SHIPMENT_1000324895_FIXTURE)
    out = appointment_scheduling_display_fields_from_payload(SHIPMENT_1000324895_FIXTURE)
    assert standard.customer_name == "DIAMOND PET FOODS"
    assert out.customer_name == "PETCO DC 810"
    assert out.carrier_name == standard.carrier_name
    assert out.pickup_date == standard.pickup_date
    assert out.pickup_timezone == standard.pickup_timezone
    assert out.delivery_date == standard.delivery_date
    assert out.delivery_timezone == standard.delivery_timezone
    assert out.carrier_name == "Turvo Test Carrier"
    assert out.pickup_date == datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
    assert out.pickup_timezone == "America/Los_Angeles"
    assert out.delivery_date == datetime(2026, 4, 1, 7, 1, tzinfo=timezone.utc)
    assert out.delivery_timezone == "America/New_York"


def test_shipment_display_fields_skips_deleted_carrier_order() -> None:
    payload = {
        "details": {
            "carrierOrder": [
                {"deleted": True, "carrier": {"name": "Deleted Carrier"}},
            ],
            "customerOrder": [],
            "globalRoute": [],
        }
    }
    out = shipment_display_fields_from_payload(payload)
    assert out.carrier_name is None


def test_shipment_display_fields_customer_order_route_fallback() -> None:
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Acme"},
                    "route": [
                        {
                            "deleted": False,
                            "appointment": {
                                "start": "2026-05-15T10:00:00Z",
                                "timeZone": "America/Chicago",
                            },
                        }
                    ],
                }
            ],
            "carrierOrder": [],
            "globalRoute": [],
        }
    }
    out = shipment_display_fields_from_payload(payload)
    assert out.customer_name == "Acme"
    assert out.delivery_date == datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    assert out.delivery_timezone == "America/Chicago"


def test_delivery_appointment_from_payload_customer_order_fallback() -> None:
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "route": [
                        {
                            "deleted": False,
                            "appointment": {"start": "2026-05-15T10:00:00Z", "timeZone": "America/Chicago"},
                        }
                    ],
                }
            ],
            "globalRoute": [],
        }
    }
    at, tz = delivery_appointment_from_payload(payload)
    assert at == datetime(2026, 5, 15, 10, 0, tzinfo=timezone.utc)
    assert tz == "America/Chicago"


def test_shipment_display_fields_empty_payload() -> None:
    out = shipment_display_fields_from_payload({})
    assert out.customer_name is None
    assert out.carrier_name is None
    assert out.pickup_date is None
    assert out.delivery_date is None
