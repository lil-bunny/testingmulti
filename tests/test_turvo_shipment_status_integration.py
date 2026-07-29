"""Tests for Turvo shipment status integration helpers."""

from __future__ import annotations

from app.integrations.turvo.shipment_status import (
    build_tender_status_body,
    fragment_id_from_shipment_payload,
    status_code_key_from_shipment_payload,
    timezone_from_shipment_payload,
)
from app.integrations.turvo.webhook_mapping import TENDERED_STATUS_CODE_KEY


def test_fragment_id_from_app_api_payload() -> None:
    payload = {
        "details": {
            "global_route": {
                "fragments": [{"fragment_id": "abc-123-def"}],
            }
        }
    }
    assert fragment_id_from_shipment_payload(payload) == "abc-123-def"


def test_status_code_key_from_payload() -> None:
    payload = {"details": {"status": {"code": {"key": "2118", "value": "Tender - accepted"}}}}
    assert status_code_key_from_shipment_payload(payload) == "2118"


def test_timezone_from_delivery_stop() -> None:
    payload = {
        "details": {
            "globalRoute": [
                {"appointment": {"timeZone": "America/Chicago"}},
                {"appointment": {"timeZone": "America/Los_Angeles"}},
            ]
        }
    }
    assert timezone_from_shipment_payload(payload) == "America/Los_Angeles"


def test_build_tender_status_body() -> None:
    body = build_tender_status_body(fragment_id="fid-1", timezone="US/Pacific")
    assert body["fragment_id"] == "fid-1"
    assert body["timezone"] == "US/Pacific"
    assert body["code"]["key"] == TENDERED_STATUS_CODE_KEY
    assert body["code"]["value"] == "Tendered"
    assert body["componentKey"] == 11033
