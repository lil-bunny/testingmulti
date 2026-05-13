"""Shared Turvo samples for E2E (PUT status fragment). Webhook envelopes live in ``fixtures/main.py``."""

from __future__ import annotations

from typing import Any

# Sandbox / app API body for ``POST .../api/shipments/status/{id}?fullResponse=true``.
ROUTE_COMPLETE_STATUS_FRAGMENT: dict[str, Any] = {
    "timezone": "US/Pacific",
    "tags": [],
    "fragment_id": "dc699a27-a652-4e75-af5f-a90575ccd371",
    "notes": "",
    "description": "Route complete",
    "code": {"id": 116038, "key": "2116", "value": "Route complete"},
    "sharing": {"notes": {"entities": []}},
    "reason": {},
    "componentKey": 11033,
}
