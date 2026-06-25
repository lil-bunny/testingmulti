"""Unit tests for Turvo pickup appointment parsing."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.integrations.turvo.shipments import (
    driver_assigned_from_payload,
    pickup_appointment_from_payload,
)

_PICKUP_FIXTURE: dict = {
    "details": {
        "globalRoute": [
            {
                "deleted": False,
                "stopType": {"value": "pickup"},
                "name": "Diamond Pet Foods - Ripon",
                "appointment": {
                    "date": "2026-03-30T15:30:00Z",
                    "timeZone": "America/Los_Angeles",
                },
            },
            {
                "deleted": False,
                "stopType": {"value": "delivery"},
                "appointment": {"date": "2026-04-01T07:01:00Z"},
            },
        ],
        "carrierOrder": [
            {
                "deleted": False,
                "carrier": {"name": "Turvo Test Carrier"},
            }
        ],
    }
}


def test_pickup_appointment_from_global_route() -> None:
    pickup = pickup_appointment_from_payload(_PICKUP_FIXTURE)
    assert pickup is not None
    assert pickup.at_utc == datetime(2026, 3, 30, 15, 30, tzinfo=timezone.utc)
    assert pickup.timezone == "America/Los_Angeles"
    assert pickup.source == "globalRoute.appointment.date"


def test_pickup_appointment_customer_order_route_fallback() -> None:
    payload = {
        "details": {
            "globalRoute": [],
            "customerOrder": [
                {
                    "deleted": False,
                    "route": [
                        {
                            "deleted": False,
                            "stopType": {"value": "pickup"},
                            "appointment": {"start": "2026-05-15T10:00:00Z"},
                        }
                    ],
                }
            ],
        }
    }
    pickup = pickup_appointment_from_payload(payload)
    assert pickup is not None
    assert pickup.source == "customerOrder.route.appointment.start"


def test_pickup_appointment_start_date_fallback() -> None:
    payload = {
        "details": {
            "globalRoute": [],
            "customerOrder": [],
            "startDate": {"date": "2026-06-01T08:00:00Z"},
        }
    }
    pickup = pickup_appointment_from_payload(payload)
    assert pickup is not None
    assert pickup.source == "details.startDate.date"


def test_pickup_appointment_missing_returns_none() -> None:
    assert pickup_appointment_from_payload({"details": {"globalRoute": []}}) is None


@pytest.mark.parametrize("payload", [{}, None, "bad"])
def test_pickup_appointment_invalid_payload(payload) -> None:
    assert pickup_appointment_from_payload(payload) is None


def test_driver_assigned_from_primary_driver() -> None:
    payload = {
        "details": {
            "globalRoute": [],
            "carrierOrder": [
                {
                    "deleted": False,
                    "primaryDriver": {"id": "drv-1", "name": "Alex"},
                }
            ],
        }
    }
    assert driver_assigned_from_payload(payload) is True


def test_driver_assigned_from_actual_pickup() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {
                    "deleted": False,
                    "stopType": {"value": "pickup"},
                    "actual": {"checkIn": "2026-03-30T16:00:00Z"},
                }
            ],
            "carrierOrder": [],
        }
    }
    assert driver_assigned_from_payload(payload) is True


def test_driver_not_assigned() -> None:
    assert driver_assigned_from_payload(_PICKUP_FIXTURE) is False


def test_driver_assigned_ignores_deleted_driver_entry_with_stale_contact() -> None:
    """Turvo keeps phone/email on drivers[] after delete; must not block enqueue."""
    payload = {
        "details": {
            "globalRoute": [],
            "carrierOrder": [
                {
                    "deleted": False,
                    "carrier": {"name": "Turvo Test Carrier"},
                    "drivers": [
                        {
                            "deleted": True,
                            "context": {"name": "Drish-test"},
                            "phone": {"number": "9876543210"},
                            "email": {"email": "drishtavya@theagentic.ai"},
                        }
                    ],
                }
            ],
        }
    }
    assert driver_assigned_from_payload(payload) is False


def test_driver_assigned_ignores_deleted_carrier_order_drivers() -> None:
    payload = {
        "details": {
            "globalRoute": [],
            "carrierOrder": [
                {
                    "deleted": True,
                    "drivers": [
                        {
                            "deleted": False,
                            "context": {"name": "Amit D"},
                            "phone": {"number": "8637823334"},
                        }
                    ],
                }
            ],
        }
    }
    assert driver_assigned_from_payload(payload) is False


def test_driver_assigned_from_active_drivers_list() -> None:
    payload = {
        "details": {
            "globalRoute": [],
            "carrierOrder": [
                {
                    "deleted": False,
                    "drivers": [
                        {
                            "deleted": False,
                            "phone": {"number": "9876543210"},
                        }
                    ],
                }
            ],
        }
    }
    assert driver_assigned_from_payload(payload) is True


def test_driver_assigned_from_context_only_driver_row() -> None:
    """Turvo often stores id/name under context without top-level phone/email."""
    payload = {
        "details": {
            "globalRoute": [],
            "carrierOrder": [
                {
                    "deleted": False,
                    "drivers": [
                        {
                            "deleted": False,
                            "context": {"id": 604186, "name": "Alyssa Wolf"},
                            "segmentId": "seg-1",
                        }
                    ],
                }
            ],
        }
    }
    assert driver_assigned_from_payload(payload) is True
