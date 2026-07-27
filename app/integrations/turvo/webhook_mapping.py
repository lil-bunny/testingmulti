"""
Map Turvo webhook JSON to internal pod_lifecycle payload.

Turvo payload shapes vary by event; extend extractors as you lock onto real samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ROUTE_COMPLETED_STATUS_CODE_KEY = "2116"
TENDERED_STATUS_CODE_KEY = "2101"
TENDER_ACCEPTED_STATUS_CODE_KEY = "2118"


@dataclass(frozen=True)
class TurvoStatusWebhookEvent:
    status_key: str
    shipment_id: str | None
    load_id: str | None


def extract_shipment_and_load_ids(body: dict[str, Any]) -> tuple[str | None, str | None]:
    """Best-effort extraction of shipment_id and load_id from a Turvo webhook body."""
    shipment_id = body.get("shipment_id") or body.get("shipmentId")
    load_id = body.get("load_id") or body.get("loadId")

    # Public API: SHIPMENT_STATUS_UPDATE, etc. - shipment is often under eventPayload.id
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


def extract_status_code_key(body: dict[str, Any]) -> str | None:
    """Extract Turvo status code key from eventPayload.status.code.key."""
    event_payload = body.get("eventPayload")
    if not isinstance(event_payload, dict):
        return None

    status = event_payload.get("status")
    if not isinstance(status, dict):
        return None

    code = status.get("code")
    if not isinstance(code, dict):
        return None

    key = code.get("key")
    return str(key) if key is not None else None


def map_turvo_status_webhook(body: dict[str, Any]) -> TurvoStatusWebhookEvent | None:
    """Parse Turvo status webhook for Tendered (2101) or Route complete (2116)."""
    shipment_id, load_id = extract_shipment_and_load_ids(body)
    status_code_key = extract_status_code_key(body)
    if status_code_key not in (
        ROUTE_COMPLETED_STATUS_CODE_KEY,
        TENDERED_STATUS_CODE_KEY,
    ):
        return None
    if not (shipment_id or load_id):
        return None
    return TurvoStatusWebhookEvent(
        status_key=status_code_key,
        shipment_id=shipment_id,
        load_id=load_id,
    )


def should_run_pod_workflow(
    shipment_id: str | None,
    load_id: str | None,
    status_code_key: str | None,
) -> bool:
    """Run only for Route complete status key (2116) with at least one stable id."""
    if status_code_key != ROUTE_COMPLETED_STATUS_CODE_KEY:
        return False
    return bool(shipment_id or load_id)


def map_turvo_status_webhook_to_payload(body: dict[str, Any]) -> dict[str, Any] | None:
    """
    Build workflow payload for a Turvo status-style webhook.

    Returns None unless:
    - eventPayload.status.code.key == "2116" (Route complete), and
    - shipment_id or load_id can be extracted.
    """
    shipment_id, load_id = extract_shipment_and_load_ids(body)
    status_code_key = extract_status_code_key(body)
    if not should_run_pod_workflow(shipment_id, load_id, status_code_key):
        return None

    payload: dict[str, Any] = {
        "event_type": "route_completed",
    }
    if shipment_id:
        payload["shipment_id"] = shipment_id
    if load_id:
        payload["load_id"] = load_id

    return payload
