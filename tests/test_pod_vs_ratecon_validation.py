"""Unit tests for POD vs RateCon field comparison (carrier not compared)."""

from __future__ import annotations

from unittest.mock import patch

from app.services.pod_lifecycle.vs_ratecon_validation import validate_pod_against_ratecon


def _base_pod(**overrides):
    data = {
        "po_number": "12345",
        "carrier_name": "POD Carrier Inc",
        "pickup_location": "Warehouse A",
        "pickup_address": "100 Main St",
        "destination_location": "Store B",
        "destination_address": "200 Oak Ave",
        "signature_present": True,
        "stamp_present": True,
        "delivery_confirmed": True,
    }
    data.update(overrides)
    return data


def _base_ratecon(**overrides):
    data = {
        "po_number": "12345",
        "carrier_name": "RateCon Carrier LLC",
        "pickup_location": "Warehouse A",
        "pickup_address": "100 Main St",
        "delivery_location": "Store B",
        "delivery_address": "200 Oak Ave",
        "shipment_identifiers": ["12345"],
        "broker_name": "T3RA LOGISTICS",
    }
    data.update(overrides)
    return data


def test_carrier_is_not_compared() -> None:
    report = validate_pod_against_ratecon(_base_pod(), _base_ratecon())

    assert all(r["field"] != "carrier_name" for r in report["field_validations"])
    assert report["overall_status"] == "PASS"


@patch(
    "app.services.pod_lifecycle.vs_ratecon_validation.ask_llm_for_semantic_match",
    return_value=(False, "denied"),
)
def test_scored_field_fail_still_fails_overall(_mock_llm) -> None:
    report = validate_pod_against_ratecon(
        _base_pod(po_number="99999"),
        _base_ratecon(),
    )

    po = next(r for r in report["field_validations"] if r["field"] == "po_number")
    assert po["status"] == "FAIL"
    assert report["overall_status"] == "FAIL"


def test_compared_fields_are_po_and_locations_only() -> None:
    report = validate_pod_against_ratecon(_base_pod(), _base_ratecon())
    fields = {r["field"] for r in report["field_validations"]}
    assert fields == {
        "po_number",
        "pickup_location",
        "pickup_address",
        "destination_location",
        "destination_address",
    }
