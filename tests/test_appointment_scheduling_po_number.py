"""Unit tests for appointment scheduling PO resolution."""

from __future__ import annotations

from app.tools.appointment_scheduling.po_number import resolve_scheduling_po_number


def _turvo_payload(*, po_numbers: str | list[str], deleted: bool = False) -> dict:
    return {
        "details": {
            "globalRoute": [
                {
                    "stopType": {"value": "Pickup"},
                    "name": "Origin",
                    "deleted": False,
                },
                {
                    "stopType": {"value": "Delivery"},
                    "name": "Costco DC",
                    "poNumbers": po_numbers,
                    "deleted": deleted,
                },
            ]
        }
    }


def test_resolve_costco_po_from_turvo_delivery_stop() -> None:
    po = resolve_scheduling_po_number(
        customer_name="Costco Wholesale #584",
        turvo_payload=_turvo_payload(po_numbers="006900520275"),
        pickup_dropoff={"po_number": "PICKUP-PO"},
    )
    assert po == "006900520275"


def test_resolve_costco_po_joins_list_values() -> None:
    po = resolve_scheduling_po_number(
        customer_name="Pet Food Experts",
        turvo_payload=_turvo_payload(po_numbers=["PO-A", "PO-B"]),
        pickup_dropoff=None,
    )
    assert po == "PO-A,PO-B"


def test_resolve_costco_po_uses_last_active_delivery_stop() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {"stopType": {"value": "Pickup"}, "deleted": False},
                {
                    "stopType": {"value": "Delivery"},
                    "poNumbers": "OLD-PO",
                    "deleted": True,
                },
                {
                    "stopType": {"value": "Delivery"},
                    "purchase_orders": "FINAL-PO",
                    "deleted": False,
                },
            ]
        }
    }
    po = resolve_scheduling_po_number(
        customer_name="Costco",
        turvo_payload=payload,
        pickup_dropoff=None,
    )
    assert po == "FINAL-PO"


def test_resolve_non_costco_po_from_ascend_pickup() -> None:
    po = resolve_scheduling_po_number(
        customer_name="Diamond Pet Foods",
        turvo_payload=_turvo_payload(po_numbers="TURVO-PO"),
        pickup_dropoff={"po_number": "A1165831,A1165817"},
    )
    assert po == "A1165831,A1165817"


def test_resolve_returns_empty_when_po_missing() -> None:
    assert (
        resolve_scheduling_po_number(
            customer_name="Other Customer",
            turvo_payload=None,
            pickup_dropoff={},
        )
        == ""
    )
    assert (
        resolve_scheduling_po_number(
            customer_name="Costco",
            turvo_payload={"details": {"globalRoute": []}},
            pickup_dropoff=None,
        )
        == ""
    )
