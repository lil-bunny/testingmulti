"""Turvo status webhook mapping tests."""

from __future__ import annotations

from app.integrations.turvo.webhook_mapping import (
    ROUTE_COMPLETED_STATUS_CODE_KEY,
    TENDERED_STATUS_CODE_KEY,
    TENDER_ACCEPTED_STATUS_CODE_KEY,
    map_turvo_status_webhook,
    map_turvo_status_webhook_to_payload,
)


def _status_body(*, status_key: str, shipment_id: str = "1000324895", load_id: str = "30389") -> dict:
    return {
        "eventPayload": {
            "id": shipment_id,
            "load": {"id": load_id},
            "status": {"code": {"key": status_key, "value": "ignored"}},
        }
    }


def test_map_turvo_status_webhook_tender_accepted() -> None:
    event = map_turvo_status_webhook(
        _status_body(status_key=TENDER_ACCEPTED_STATUS_CODE_KEY)
    )
    assert event is None


def test_map_turvo_status_webhook_tendered() -> None:
    event = map_turvo_status_webhook(_status_body(status_key=TENDERED_STATUS_CODE_KEY))
    assert event is not None
    assert event.status_key == TENDERED_STATUS_CODE_KEY
    assert event.shipment_id == "1000324895"
    assert event.load_id == "30389"


def test_map_turvo_status_webhook_route_completed() -> None:
    event = map_turvo_status_webhook(_status_body(status_key=ROUTE_COMPLETED_STATUS_CODE_KEY))
    assert event is not None
    assert event.status_key == ROUTE_COMPLETED_STATUS_CODE_KEY


def test_map_turvo_status_webhook_to_payload_still_route_completed_only() -> None:
    payload = map_turvo_status_webhook_to_payload(
        _status_body(status_key=ROUTE_COMPLETED_STATUS_CODE_KEY)
    )
    assert payload == {
        "event_type": "route_completed",
        "shipment_id": "1000324895",
        "load_id": "30389",
    }

    assert map_turvo_status_webhook_to_payload(
        _status_body(status_key=TENDERED_STATUS_CODE_KEY)
    ) is None


def test_map_turvo_status_webhook_unknown_status() -> None:
    assert map_turvo_status_webhook(_status_body(status_key="2102")) is None
