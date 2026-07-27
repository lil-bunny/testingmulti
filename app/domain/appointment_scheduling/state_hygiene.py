"""Pure helpers to slim appointment_scheduling LangGraph checkpoint data."""

from __future__ import annotations

from typing import Any

INTAKE_CHECKPOINT_STRIP_KEYS: tuple[str, ...] = (
    "shipment",
    "ascend_shipment",
    "draft_static",
    "ascend_context",
    "email_draft",
    "llm_appointment_decision",
    "appointment_payload",
    # Set early on intake before lifecycle transitions; send/reply runs hydrate fresh.
    "workflow_lifecycle_status",
    "workflow_lifecycle_sub_status",
)


def strip_intake_checkpoint_data(data: dict[str, Any]) -> None:
    """Remove vendor blobs and persisted intake keys from in-run state."""
    for key in INTAKE_CHECKPOINT_STRIP_KEYS:
        data.pop(key, None)


def slim_turvo_write_result(
    *,
    ok: bool,
    updated: bool = False,
    skipped: bool = False,
    error: str | None = None,
    stop_name: str | None = None,
    start_time: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": ok, "updated": updated}
    if skipped:
        out["skipped"] = True
    if error:
        out["error"] = error
    if stop_name:
        out["stop_name"] = stop_name
    if start_time:
        out["start_time"] = start_time
    return out


def slim_ascend_write_result(
    *,
    ok: bool,
    skipped: bool = False,
    dry_run: bool = False,
    error: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": ok}
    if skipped:
        out["skipped"] = skipped
    if dry_run:
        out["dry_run"] = dry_run
    if error:
        out["error"] = error
    return out


def slim_weekend_pickup_result(
    *,
    ok: bool,
    skipped: bool = False,
    dry_run: bool = False,
    error: str | None = None,
    ascend_updated: bool = False,
    turvo_updated: bool = False,
    turvo_pickup_start_time: str | None = None,
    pickup_stop_name: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": ok}
    if skipped:
        out["skipped"] = skipped
    if dry_run:
        out["dry_run"] = dry_run
    if error:
        out["error"] = error
    if ascend_updated:
        out["ascend_updated"] = ascend_updated
    if turvo_updated:
        out["turvo_updated"] = turvo_updated
    if turvo_pickup_start_time:
        out["turvo_pickup_start_time"] = turvo_pickup_start_time
    if pickup_stop_name:
        out["pickup_stop_name"] = pickup_stop_name
    return out
