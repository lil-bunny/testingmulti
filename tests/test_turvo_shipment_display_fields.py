"""Unit tests for Turvo shipment display field extraction."""

from __future__ import annotations

from datetime import date

from app.integrations.turvo.shipments import shipment_display_fields_from_payload

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
            },
            {
                "deleted": False,
                "name": "PETCO DC 810",
                "address": {"city": "CRANBURY", "state": "NJ"},
                "appointment": {"date": "2026-04-01T07:01:00Z"},
            },
        ],
    }
}


def test_shipment_display_fields_from_payload_full_fixture() -> None:
    out = shipment_display_fields_from_payload(SHIPMENT_1000324895_FIXTURE)
    assert out.customer_name == "DIAMOND PET FOODS"
    assert out.carrier_name == "Turvo Test Carrier"
    assert out.delivery_date == date(2026, 4, 1)


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
                            "appointment": {"start": "2026-05-15T10:00:00Z"},
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
    assert out.delivery_date == date(2026, 5, 15)


def test_shipment_display_fields_empty_payload() -> None:
    out = shipment_display_fields_from_payload({})
    assert out.customer_name is None
    assert out.carrier_name is None
    assert out.delivery_date is None
