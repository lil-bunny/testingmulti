"""Unit tests for Turvo driver-request eligibility parsing."""

from __future__ import annotations

import pytest

from app.integrations.turvo.shipments import (
    COVERED_STATUS_CODE_KEY,
    TL_TRANSPORTATION_MODE_KEY,
    driver_request_eligible_from_payload,
)


def _eligible_payload(**details_overrides) -> dict:
    details = {
        "transportation": {"mode": {"key": TL_TRANSPORTATION_MODE_KEY, "value": "TL"}},
        "status": {"code": {"key": COVERED_STATUS_CODE_KEY, "value": "Covered"}},
        "carrierOrder": [
            {
                "deleted": False,
                "carrier": {"name": "Turvo Test Carrier"},
            }
        ],
        "globalRoute": [],
    }
    details.update(details_overrides)
    return {"details": details}


def test_driver_request_eligible_happy_path() -> None:
    assert driver_request_eligible_from_payload(_eligible_payload()) is None


@pytest.mark.parametrize("payload", [{}, None, "bad"])
def test_driver_request_eligible_invalid_payload(payload) -> None:
    assert driver_request_eligible_from_payload(payload) == "shipment_not_in_state"


def test_driver_request_eligible_wrong_mode() -> None:
    payload = _eligible_payload(
        transportation={"mode": {"key": "24104", "value": "LTL"}},
    )
    assert driver_request_eligible_from_payload(payload) == "transportation_mode_not_tl"


def test_driver_request_eligible_missing_mode() -> None:
    payload = _eligible_payload(transportation={})
    assert driver_request_eligible_from_payload(payload) == "transportation_mode_not_tl"


@pytest.mark.parametrize(
    "status_key",
    ["2101", "2118", "2116"],
)
def test_driver_request_eligible_not_covered(status_key: str) -> None:
    payload = _eligible_payload(
        status={"code": {"key": status_key, "value": "not-covered"}},
    )
    assert driver_request_eligible_from_payload(payload) == "shipment_not_covered"


def test_driver_request_eligible_excluded_palacio() -> None:
    payload = _eligible_payload(
        carrierOrder=[
            {
                "deleted": False,
                "carrier": {"name": "A&V Palacio Truck Lines"},
            }
        ],
    )
    assert driver_request_eligible_from_payload(payload) == "excluded_carrier"


def test_driver_request_eligible_excluded_convoy() -> None:
    payload = _eligible_payload(
        carrierOrder=[
            {
                "deleted": False,
                "carrier": {"name": "Convoy Platform"},
            }
        ],
    )
    assert driver_request_eligible_from_payload(payload) == "excluded_carrier"


def test_driver_request_eligible_ignores_deleted_excluded_carrier() -> None:
    payload = _eligible_payload(
        carrierOrder=[
            {
                "deleted": True,
                "carrier": {"name": "A&V Palacio Truck Lines"},
            },
            {
                "deleted": False,
                "carrier": {"name": "Turvo Test Carrier"},
            },
        ],
    )
    assert driver_request_eligible_from_payload(payload) is None
