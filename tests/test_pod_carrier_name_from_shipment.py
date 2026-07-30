"""Tests for ``_carrier_name_from_shipment`` (Turvo carrier → POD broker_name)."""

from __future__ import annotations

from app.tools.pod import _carrier_name_from_shipment


def test_returns_carrier_name_from_first_order():
    data = {
        "shipment": {
            "details": {
                "carrierOrder": [
                    {"id": 1, "carrier": {"name": "Bajwa Truckers Inc", "id": 5853937}}
                ]
            }
        }
    }
    assert _carrier_name_from_shipment(data) == "Bajwa Truckers Inc"


def test_strips_whitespace():
    data = {
        "shipment": {
            "details": {"carrierOrder": [{"carrier": {"name": "  Acme Freight  "}}]}
        }
    }
    assert _carrier_name_from_shipment(data) == "Acme Freight"


def test_none_when_no_shipment():
    assert _carrier_name_from_shipment({}) is None


def test_none_when_carrier_order_empty():
    data = {"shipment": {"details": {"carrierOrder": []}}}
    assert _carrier_name_from_shipment(data) is None


def test_none_when_carrier_order_missing():
    data = {"shipment": {"details": {}}}
    assert _carrier_name_from_shipment(data) is None


def test_none_when_carrier_name_blank():
    data = {"shipment": {"details": {"carrierOrder": [{"carrier": {"name": "   "}}]}}}
    assert _carrier_name_from_shipment(data) is None


def test_none_when_details_not_a_dict():
    data = {"shipment": {"details": None}}
    assert _carrier_name_from_shipment(data) is None
