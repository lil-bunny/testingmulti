"""Live Turvo Public API smoke tests (opt-in).

Requires a working ``.env`` (``TURVO_PUBLICAPI_URL``, DB, etc.) and a Turvo account
with stored OAuth tokens for the tenant slug you pass.

Print responses to the terminal::

    # PowerShell
    $env:TURVO_LIVE_TEST='1'
    $env:TURVO_LIVE_TENANT_SLUG='t3ra'   # optional if TURVO_DEFAULT_TENANT_SLUG is set
    $env:PYTHONPATH='C:\\freightx-agents'
    uv run pytest tests/test_turvo_shipment_live.py -s -v

Skip reason: set ``TURVO_LIVE_TEST=1`` (or ``true``) to run.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from app.core.config import settings
from app.integrations.turvo import documents as documents_module
from app.integrations.turvo.shipments import get_shipment

LIVE_SHIPMENT_ID = "1000304706"


def _live_enabled() -> bool:
    v = os.environ.get("TURVO_LIVE_TEST", "").strip().lower()
    return v in ("1", "true", "yes")


def _live_tenant_slug() -> str | None:
    explicit = os.environ.get("TURVO_LIVE_TENANT_SLUG", "").strip()
    if explicit:
        return explicit
    legacy = os.environ.get("TURVO_LIVE_APP_USER_ID", "").strip()
    if legacy:
        return legacy
    return (settings.TURVO_DEFAULT_TENANT_SLUG or "").strip() or None


def _skip_live(reason: str) -> None:
    pytest.skip(reason)


@pytest.mark.asyncio
async def test_live_turvo_shipment_and_pod_check_prints_json():
    """GET shipment + documents-join POD check; prints JSON (run with ``pytest -s``)."""
    if not _live_enabled():
        _skip_live("Set TURVO_LIVE_TEST=1 to hit Turvo (see module docstring).")

    if not settings.TURVO_PUBLICAPI_URL:
        _skip_live("TURVO_PUBLICAPI_URL is not set.")

    tenant_slug = _live_tenant_slug()
    if not tenant_slug:
        _skip_live(
            "No tenant slug: set TURVO_LIVE_TENANT_SLUG or TURVO_DEFAULT_TENANT_SLUG in .env."
        )

    shipment: dict[str, Any] = await get_shipment(tenant_slug, LIVE_SHIPMENT_ID)
    pod: dict[str, Any] = await documents_module.check_pod_by_shipment_id(
        tenant_slug, LIVE_SHIPMENT_ID
    )

    print("\n=== Turvo GET /v1/shipments/{id} (no join params) ===\n")
    print(json.dumps(shipment, indent=2, default=str))

    print("\n=== check_pod_by_shipment_id (GET /v1/documents/list + POD detection) ===\n")
    print(json.dumps(pod, indent=2, default=str))

    assert isinstance(shipment, dict)
    assert isinstance(pod, dict)
    assert pod.get("shipment_id") == LIVE_SHIPMENT_ID
    assert "pod_exists" in pod
    assert "success" in pod
