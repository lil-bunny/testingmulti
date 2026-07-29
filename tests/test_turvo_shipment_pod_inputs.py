"""Unit tests for Turvo PoD-scoring inputs extraction (``extract_pod_inputs_from_shipment``).

Inline fixtures mirror ``scripts/pod-scoring-model-v2/shipments.json`` shape
(single pickup/delivery, different ``poNumbers`` per stop).
"""

from __future__ import annotations

from app.integrations.turvo.pod_inputs import (
    TurvoPurchaseOrder,
    extract_pod_inputs_from_shipment,
)

_SHIPMENT_62762_FIXTURE: dict = {
    "details": {
        "customId": "62762",
        "startDate": {"date": "2026-07-20T15:00:00Z", "timeZone": "America/Los_Angeles"},
        "endDate": {"date": "2026-07-21T13:00:00Z", "timeZone": "America/Los_Angeles"},
        "globalRoute": [
            {
                "name": "Diamond Pet Foods - 95330 (Roth)",
                "id": 292991470,
                "stopType": {"key": "1500", "value": "Pickup"},
                "timezone": "America/Los_Angeles",
                "address": {
                    "city": "Lathrop",
                    "state": "CA",
                    "countryCode": "US",
                    "line1": "250 East Roth Road",
                },
                "poNumbers": ["A1176371"],
                "notes": "Pallets: 37 | Weight: 43420 LB",
                "deleted": False,
            },
            {
                "name": "COSTCO # 766",
                "id": 292991471,
                "stopType": {"key": "1501", "value": "Delivery"},
                "timezone": "America/Los_Angeles",
                "address": {
                    "city": "WILSONVILLE",
                    "state": "OR",
                    "countryCode": "US",
                    "line1": "25900 HEATHER PLACE",
                },
                "poNumbers": ["007660706282"],
                "notes": "Pallets: 37 | Weight: 43420 LB",
                "deleted": False,
            },
        ],
    }
}


def test_shipment_pod_inputs_from_real_sample_payload() -> None:
    pod_inputs = extract_pod_inputs_from_shipment(_SHIPMENT_62762_FIXTURE)

    assert pod_inputs.is_single_stop is True
    assert pod_inputs.pickup.name == "Diamond Pet Foods - 95330 (Roth)"
    assert pod_inputs.pickup.address == "250 East Roth Road, Lathrop, CA, US"
    assert pod_inputs.delivery.name == "COSTCO # 766"
    assert pod_inputs.delivery.address == "25900 HEATHER PLACE, WILSONVILLE, OR, US"
    assert pod_inputs.pickup_date == "2026-07-20T15:00:00Z"
    assert pod_inputs.delivery_date == "2026-07-21T13:00:00Z"
    assert pod_inputs.ordered_pallet_qty == 37
    assert pod_inputs.custom_id == "62762"


def test_purchase_orders_are_flattened_and_stop_tagged() -> None:
    """Pickup and delivery poNumbers stay independent POs, never unioned into one pool."""
    pod_inputs = extract_pod_inputs_from_shipment(_SHIPMENT_62762_FIXTURE)

    assert pod_inputs.purchase_orders == [
        TurvoPurchaseOrder(po_number="A1176371", stop_type="pickup", stop_id="292991470"),
        TurvoPurchaseOrder(po_number="007660706282", stop_type="delivery", stop_id="292991471"),
    ]
    assert pod_inputs.pickup.po_numbers == ["A1176371"]
    assert pod_inputs.delivery.po_numbers == ["007660706282"]


def test_multi_po_on_one_stop_produces_one_po_per_entry() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {
                    "name": "Shipper",
                    "stopType": {"key": "1500", "value": "Pickup"},
                    "address": {"city": "Reno", "state": "NV"},
                    "poNumbers": [],
                    "deleted": False,
                },
                {
                    "name": "Consignee",
                    "stopType": {"key": "1501", "value": "Delivery"},
                    "address": {"city": "Bossier City", "state": "LA"},
                    "poNumbers": ["PO-1", "PO-2", "PO-3"],
                    "deleted": False,
                },
            ]
        }
    }
    pod_inputs = extract_pod_inputs_from_shipment(payload)

    assert pod_inputs.is_single_stop is True
    assert pod_inputs.purchase_orders == [
        TurvoPurchaseOrder(po_number="PO-1", stop_type="delivery"),
        TurvoPurchaseOrder(po_number="PO-2", stop_type="delivery"),
        TurvoPurchaseOrder(po_number="PO-3", stop_type="delivery"),
    ]


def test_multi_stop_shipment_is_not_single_stop() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {"stopType": {"key": "1500", "value": "Pickup"}, "deleted": False},
                {"stopType": {"key": "1501", "value": "Delivery"}, "deleted": False},
                {"stopType": {"key": "1501", "value": "Delivery"}, "deleted": False},
            ]
        }
    }
    pod_inputs = extract_pod_inputs_from_shipment(payload)
    assert pod_inputs.is_single_stop is False


def test_deleted_stops_are_excluded() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {
                    "name": "Deleted pickup",
                    "stopType": {"key": "1500", "value": "Pickup"},
                    "deleted": True,
                },
                {
                    "name": "Active pickup",
                    "stopType": {"key": "1500", "value": "Pickup"},
                    "address": {"city": "Reno", "state": "NV"},
                    "poNumbers": ["ONLY-PO"],
                    "deleted": False,
                },
                {
                    "name": "Active delivery",
                    "stopType": {"key": "1501", "value": "Delivery"},
                    "address": {"city": "Bossier City", "state": "LA"},
                    "deleted": False,
                },
            ]
        }
    }
    pod_inputs = extract_pod_inputs_from_shipment(payload)
    assert pod_inputs.is_single_stop is True
    assert pod_inputs.pickup.name == "Active pickup"
    assert pod_inputs.purchase_orders == [TurvoPurchaseOrder(po_number="ONLY-PO", stop_type="pickup")]


def test_missing_po_numbers_returns_empty_list_without_crashing() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {"name": "Shipper", "stopType": {"key": "1500", "value": "Pickup"}, "deleted": False},
                {"name": "Consignee", "stopType": {"key": "1501", "value": "Delivery"}, "deleted": False},
            ]
        }
    }
    pod_inputs = extract_pod_inputs_from_shipment(payload)
    assert pod_inputs.pickup.po_numbers == []
    assert pod_inputs.delivery.po_numbers == []
    assert pod_inputs.purchase_orders == []


def test_empty_payload_does_not_crash() -> None:
    pod_inputs = extract_pod_inputs_from_shipment({})
    assert pod_inputs.is_single_stop is False
    assert pod_inputs.pickup.name == ""
    assert pod_inputs.delivery.name == ""
    assert pod_inputs.purchase_orders == []
    assert pod_inputs.pickup_date is None
    assert pod_inputs.ordered_pallet_qty is None
