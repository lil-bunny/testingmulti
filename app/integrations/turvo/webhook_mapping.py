"""
Map Turvo webhook JSON to internal pod_lifecycle payload.

Turvo payload shapes vary by event; extend _extract_ids as you lock onto real samples.
"""

from __future__ import annotations

from typing import Any


def extract_shipment_and_load_ids(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort extraction of shipment_id and load_id from a Turvo webhook body."""
    shipment_id = body.get("shipment_id") or body.get("shipmentId")
    load_id = body.get("load_id") or body.get("loadId")

    # Public API: SHIPMENT_STATUS_UPDATE, etc. — shipment is often under eventPayload.id
    event_payload = body.get("eventPayload")
    if isinstance(event_payload, dict):
        if not shipment_id and event_payload.get("id") is not None:
            shipment_id = event_payload.get("id")
        if not load_id and isinstance(event_payload.get("load"), dict):
            load_id = event_payload["load"].get("id")

    data = body.get("data")
    if isinstance(data, dict):
        shipment_id = shipment_id or data.get("shipment_id") or data.get("shipmentId")
        load_id = load_id or data.get("load_id") or data.get("loadId")
        if not shipment_id:
            shipment = data.get("shipment")
            if isinstance(shipment, dict):
                shipment_id = shipment.get("id") or shipment.get("shipment_id")
        if not load_id:
            load = data.get("load")
            if isinstance(load, dict):
                load_id = load.get("id") or load.get("load_id")

    return (
        str(shipment_id) if shipment_id is not None else None,
        str(load_id) if load_id is not None else None,
    )


def should_run_pod_workflow(shipment_id: str | None, load_id: str | None) -> bool:
    """Require at least one stable id so get_shipment / correlation can run."""
    return bool(shipment_id or load_id)


def map_turvo_status_webhook_to_payload(body: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build workflow payload for a Turvo status-style webhook.

    Returns None if there is not enough data to run pod_lifecycle safely.
    """
    shipment_id, load_id = extract_shipment_and_load_ids(body)
    if not should_run_pod_workflow(shipment_id, load_id):
        return None

    payload: dict[str, Any] = {
        "event_type": "route_completed",
    }
    if shipment_id:
        payload["shipment_id"] = shipment_id
    if load_id:
        payload["load_id"] = load_id

    return payload
