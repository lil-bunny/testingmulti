"""Pure helpers for driver_assignment sequential reminder ladder."""

from __future__ import annotations

from typing import Any

from app.domain.status_parsing import sub_status_type_from_db
from app.models.status import StatusSubType

DRIVER_ASSIGNMENT_SENT_SCHEDULE_STEPS_KEY = "driver_assignment_sent_schedule_steps"
MAX_SEQUENTIAL_REMINDER_STEP = 4


def sequential_reminder_step_from_sub_status(sub_status: Any) -> int:
    """Map lifecycle sub_status to how many scheduled reminders were logged (0–4)."""
    sub = sub_status_type_from_db(sub_status)
    mapping = {
        StatusSubType.REMINDER_1_SENT: 1,
        StatusSubType.REMINDER_2_SENT: 2,
        StatusSubType.REMINDER_3_SENT: 3,
        StatusSubType.REMINDER_4_SENT: 4,
    }
    return mapping.get(sub, 0)


def sequential_reminder_step_from_lifecycle_row(row: dict[str, Any] | None) -> int:
    if not row:
        return 0
    return sequential_reminder_step_from_sub_status(row.get("sub_status"))


def next_sequential_reminder_step(current: int) -> int:
    return min(int(current) + 1, MAX_SEQUENTIAL_REMINDER_STEP)


def sent_schedule_steps_from_metadata(metadata: Any) -> frozenset[int]:
    if not isinstance(metadata, dict):
        return frozenset()
    raw = metadata.get(DRIVER_ASSIGNMENT_SENT_SCHEDULE_STEPS_KEY)
    if not isinstance(raw, list):
        return frozenset()
    out: set[int] = set()
    for item in raw:
        try:
            out.add(int(item))
        except (TypeError, ValueError):
            continue
    return frozenset(out)


def append_sent_schedule_step(existing: list[int], step: int) -> list[int]:
    value = int(step)
    merged = list(existing)
    if value not in merged:
        merged.append(value)
    merged.sort()
    return merged


def schedule_reminder_step_from_payload(payload: dict[str, Any]) -> int | None:
    """Schedule slot from tenant config; falls back to legacy reminder_step in payload."""
    raw = payload.get("schedule_reminder_step")
    if raw is None:
        raw = payload.get("reminder_step")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def should_resolve_sequential_reminder_step(payload: dict[str, Any]) -> bool:
    """True for scheduled/partial driver reminders, not confirmation emails."""
    source = str(payload.get("reminder_email_source") or "driver_assignment_reminder").strip()
    if source == "driver_details_confirmation":
        return False
    if payload.get("schedule_reminder_step") is not None:
        return True
    if str(payload.get("event_type") or "").strip() == "reminder_due":
        return True
    return source in {
        "driver_assignment_reminder",
        "driver_details_partial_follow_up",
    }
