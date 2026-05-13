"""Central E2E webhook payloads (JSON under this directory)."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

_FIXTURE_DIR = Path(__file__).resolve().parent


def _load_json(name: str) -> dict:
    path = _FIXTURE_DIR / name
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


POD_REPLY_WEBHOOK_PAYLOAD = _load_json("pod_reply_webhook_payload.json")
RATECON_WEBHOOK_PAYLOAD = _load_json("ratecon_webhook_payload.json")
ROUTE_COMPLETE_WEBHOOK_PAYLOAD = _load_json("route_complete_webhook_payload.json")


def route_complete_webhook_for_shipment(shipment_id: int) -> dict:
    """``SHIPMENT_STATUS_UPDATE`` envelope for ``POST /api/listen_turvo_status`` (copy + id)."""
    body = deepcopy(ROUTE_COMPLETE_WEBHOOK_PAYLOAD)
    ep = body.get("eventPayload")
    if not isinstance(ep, dict):
        body["eventPayload"] = {"id": int(shipment_id)}
    else:
        ep["id"] = int(shipment_id)
    return body
