from app.integrations.turvo.webhook_mapping import map_turvo_status_webhook_to_payload


def test_shipment_status_update_payload_extracts_shipment_id_for_route_complete():
    body = {
        "tenantId": "1203",
        "eventName": "SHIPMENT_STATUS_UPDATE",
        "eventTime": "2026-04-27T10:46:48.245Z",
        "eventPayload": {
            "id": 1000304706,
            "status": {"code": {"key": "2116", "value": "Route complete"}},
        },
    }
    payload = map_turvo_status_webhook_to_payload(body)
    assert payload is not None
    assert payload["event_type"] == "route_completed"
    assert payload["shipment_id"] == "1000304706"


def test_shipment_status_update_payload_is_skipped_for_non_route_complete_key():
    body = {
        "tenantId": "1203",
        "eventName": "SHIPMENT_STATUS_UPDATE",
        "eventTime": "2026-04-27T10:46:48.245Z",
        "eventPayload": {
            "id": 1000304706,
            "status": {"code": {"key": "9999", "value": "In Transit"}},
        },
    }
    payload = map_turvo_status_webhook_to_payload(body)
    assert payload is None
