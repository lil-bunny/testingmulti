"""Unit tests for appointment scheduling Turvo ingress pure tools."""

from __future__ import annotations

from app.domain.appointment_scheduling.scheduling_reference import is_diamond_scheduling_reference
from app.services.appointment_scheduling.ingress_service import (
    evaluate_activity_gates,
    evaluate_parsed_webhook,
    evaluate_process_enabled,
    evaluate_shipment_gates,
)
from app.tools.appointment_scheduling.ingress import (
    is_multi_stop_shipment,
    parse_shipment_update_webhook,
    pickup_changed_in_activity_delta,
    reference_number_from_turvo_shipment,
)
from tests.test_shipment_location_link import THREE_STOP_ROUTE


def _activity_entry(*, creator: str, prev_date: str, final_date: str) -> dict:
    return {
        "record_metadata": {"created_by": {"name": creator}},
        "context_snapshot": {
            "global_route": {"ship_locations": [{"type": {"key": "1500"}}]},
            "delta": {
                "prev_diff_context": {
                    "global_route": {
                        "ship_locations": [
                            {
                                "type": {"key": "1500"},
                                "appointment": {"date": prev_date},
                            }
                        ]
                    }
                },
                "final_diff_context": {
                    "global_route": {
                        "ship_locations": [
                            {
                                "type": {"key": "1500"},
                                "appointment": {"date": final_date},
                            }
                        ]
                    }
                },
            },
        },
    }


def test_parse_shipment_update_webhook_tender_accepted() -> None:
    body = {
        "eventName": "SHIPMENT_UPDATE",
        "eventPayload": {
            "id": "12345",
            "load": {"id": "47361"},
            "status": {"code": {"value": "Tender Accepted"}},
        },
    }
    parsed = parse_shipment_update_webhook(body)
    assert parsed is not None
    assert parsed.shipment_id == "12345"
    assert parsed.load_id == "47361"
    assert parsed.tender_accepted is True


def test_parse_shipment_update_webhook_wrong_event() -> None:
    assert parse_shipment_update_webhook({"eventName": "OTHER"}) is None


def test_pickup_changed_in_activity_delta_true() -> None:
    activity = {"data": [_activity_entry(creator="Ops", prev_date="2026-03-20", final_date="2026-03-21")]}
    assert pickup_changed_in_activity_delta(activity) is True


def test_pickup_changed_in_activity_delta_false_same_date() -> None:
    activity = {"data": [_activity_entry(creator="Ops", prev_date="2026-03-20", final_date="2026-03-20")]}
    assert pickup_changed_in_activity_delta(activity) is False


def test_pickup_changed_skips_system_bot() -> None:
    activity = {
        "data": [
            _activity_entry(
                creator="Turvo System Bot",
                prev_date="2026-03-20",
                final_date="2026-03-21",
            ),
            _activity_entry(creator="Ops", prev_date="2026-03-20", final_date="2026-03-20"),
        ]
    }
    assert pickup_changed_in_activity_delta(activity) is False


def test_is_multi_stop_shipment_three_active_stops() -> None:
    payload = {"details": {"globalRoute": THREE_STOP_ROUTE}}
    assert is_multi_stop_shipment(payload) is True


def test_is_multi_stop_shipment_two_stops_false() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {"deleted": False, "name": "Pickup"},
                {"deleted": False, "name": "Delivery"},
            ]
        }
    }
    assert is_multi_stop_shipment(payload) is False


def test_is_multi_stop_shipment_ignores_deleted_stops() -> None:
    route = [
        {"deleted": False, "name": "Pickup"},
        {"deleted": True, "name": "Removed"},
        {"deleted": False, "name": "Delivery 1"},
        {"deleted": False, "name": "Delivery 2"},
    ]
    payload = {"details": {"globalRoute": route}}
    assert is_multi_stop_shipment(payload) is True


def test_is_diamond_reference() -> None:
    assert is_diamond_scheduling_reference("DIAMOND-RPN-123") is True
    assert is_diamond_scheduling_reference("ACME-1") is False


def test_reference_number_from_turvo_shipment() -> None:
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "externalIds": [{"idValue": "DIAMOND-RPN-999"}],
                }
            ]
        }
    }
    assert reference_number_from_turvo_shipment(payload) == "DIAMOND-RPN-999"


def test_reference_number_from_turvo_shipment_public_api_value_field() -> None:
    payload = {
        "customerOrder": [
            {
                "deleted": False,
                "externalIds": [
                    {
                        "type": {"key": "1401", "value": "Reference #"},
                        "value": "DIAMOND-RPN-TEST-001",
                    }
                ],
            }
        ]
    }
    assert reference_number_from_turvo_shipment(payload) == "DIAMOND-RPN-TEST-001"


def test_evaluate_process_enabled_requires_appointment_scheduling() -> None:
    assert evaluate_process_enabled({"enabledProcesses": ["pod_lifecycle"]}) == "process_disabled"
    assert (
        evaluate_process_enabled({"enabledProcesses": ["appointment_scheduling"]}) is None
    )


def test_evaluate_parsed_webhook_requires_tender_accepted() -> None:
    parsed = parse_shipment_update_webhook(_shipment_update_body(tender_accepted=False))
    assert parsed is not None
    assert evaluate_parsed_webhook(parsed) == "status_not_tender_accepted"


def test_evaluate_activity_gates_ignores_multi_stop_activity_snapshot() -> None:
    activity = {
        "data": [
            _activity_entry(creator="Ops", prev_date="2026-03-20", final_date="2026-03-21"),
        ]
    }
    activity["data"][0]["context_snapshot"]["global_route"] = {
        "ship_locations": [{}, {}, {}],
    }
    assert evaluate_activity_gates(activity) is None


def _shipment_update_body(*, tender_accepted: bool = True) -> dict:
    status = (
        {"code": {"value": "Tender-Accepted"}}
        if tender_accepted
        else {"code": {"value": "Covered"}}
    )
    return {
        "eventName": "SHIPMENT_UPDATE",
        "eventPayload": {
            "id": "12345",
            "load": {"id": "47361"},
            "status": status,
        },
    }


def test_evaluate_shipment_gates_non_diamond() -> None:
    reason, fetched = evaluate_shipment_gates(
        {"details": {"customerOrder": [{"externalIds": [{"idValue": "ACME-1"}]}]}},
        webhook_load_id="47361",
    )
    assert reason == "non_diamond_customer"
    assert fetched is None


def test_evaluate_shipment_gates_multi_stop() -> None:
    payload = {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "externalIds": [{"idValue": "DIAMOND-RPN-999"}],
                }
            ],
            "globalRoute": THREE_STOP_ROUTE,
        }
    }
    reason, fetched = evaluate_shipment_gates(payload, webhook_load_id="47361")
    assert reason == "multi_stop"
    assert fetched is None
