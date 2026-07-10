"""Synthetic ``driver_assignment`` / ``ratecon_completed`` payloads for opt-in E2E."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from app.models.workflow_run_event_type import WorkflowRunEventType


def turvo_shipment_fixture(*, pickup_at: datetime | None = None) -> dict[str, Any]:
    """Minimal TL + Covered shipment with one pickup stop (matches ingress unit tests)."""
    pickup = pickup_at or datetime(2026, 3, 30, 15, 30, 0, tzinfo=timezone.utc)
    return {
        "details": {
            "transportation": {"mode": {"key": "24105", "value": "TL"}},
            "status": {"code": {"key": "2102", "value": "Covered"}},
            "globalRoute": [
                {
                    "deleted": False,
                    "stopType": {"value": "pickup"},
                    "appointment": {
                        "date": pickup.isoformat(),
                        "timeZone": "America/Los_Angeles",
                    },
                }
            ],
            "carrierOrder": [],
        }
    }


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def driver_assignment_e2e_correlation() -> dict[str, str] | None:
    """Required env keys for full-stack driver_assignment E2E; ``None`` if incomplete."""
    keys = {
        "tenant_slug": _env("DRIVER_ASSIGNMENT_E2E_TENANT_SLUG") or "t3ra",
        "shipments_row_id": _env("DRIVER_ASSIGNMENT_E2E_SHIPMENTS_ROW_ID"),
        "shipment_id": _env("DRIVER_ASSIGNMENT_E2E_SHIPMENT_ID"),
        "load_id": _env("DRIVER_ASSIGNMENT_E2E_LOAD_ID"),
        "ratecon_workflow_lifecycle_id": _env("DRIVER_ASSIGNMENT_E2E_RATECON_LC_ID"),
        "thread_id": _env("DRIVER_ASSIGNMENT_E2E_THREAD_ID"),
    }
    missing = [k for k, v in keys.items() if k != "tenant_slug" and not v]
    if missing:
        return None
    return keys  # type: ignore[return-value]


def hours_until_pickup_from_env(*, default: float = 25.0) -> float:
    raw = _env("DRIVER_ASSIGNMENT_E2E_HOURS_UNTIL_PICKUP")
    if not raw:
        return default
    return float(raw)


def build_ratecon_completed_payload(
    correlation: dict[str, str],
    *,
    hours_until_pickup: float,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """``ratecon_completed`` payload for ``run_workflow_async`` (skips ratecon graph)."""
    now = datetime.now(timezone.utc)
    pickup_at = now + timedelta(hours=hours_until_pickup)
    payload: dict[str, Any] = {
        "event_type": WorkflowRunEventType.RATECON_COMPLETED.value,
        "tenant_slug": correlation["tenant_slug"],
        "shipments_row_id": correlation["shipments_row_id"],
        "shipment_id": correlation["shipment_id"],
        "load_id": correlation["load_id"],
        "thread_id": correlation["thread_id"],
        "ratecon_workflow_lifecycle_id": correlation["ratecon_workflow_lifecycle_id"],
        "pickup_appointment_at": pickup_at.isoformat(),
        "pickup_appointment_timezone": "America/Los_Angeles",
        "pickup_appointment_source": "globalRoute.appointment.date",
        "shipment": turvo_shipment_fixture(pickup_at=pickup_at),
    }
    if execution_id:
        payload["execution_id"] = execution_id
    return payload
