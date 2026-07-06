"""Lifecycle metadata helpers for revocable Celery reminder tasks."""

from __future__ import annotations

from typing import Any

PENDING_REMINDER_TASKS_KEY = "pending_reminder_tasks"


def pending_reminder_tasks_from_metadata(metadata: Any) -> list[dict[str, Any]]:
    """Return stored Celery task records from lifecycle metadata."""
    if not isinstance(metadata, dict):
        return []
    raw = metadata.get(PENDING_REMINDER_TASKS_KEY)
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("task_id") or "").strip():
            out.append(dict(item))
    return out


def merge_pending_reminder_tasks(
    metadata: Any,
    *,
    new_entries: list[dict[str, Any]],
) -> dict[str, Any]:
    """Metadata patch appending task records (caller merges via repository)."""
    existing = pending_reminder_tasks_from_metadata(metadata)
    merged = [*existing, *new_entries]
    return {PENDING_REMINDER_TASKS_KEY: merged}


def filter_pending_reminder_tasks(
    metadata: Any,
    *,
    remove_task_ids: frozenset[str],
) -> dict[str, Any]:
    """Metadata patch with listed Celery task ids removed."""
    kept = [
        item
        for item in pending_reminder_tasks_from_metadata(metadata)
        if str(item.get("task_id") or "").strip() not in remove_task_ids
    ]
    return {PENDING_REMINDER_TASKS_KEY: kept}


def clear_pending_reminder_tasks() -> dict[str, Any]:
    """Metadata patch clearing all pending reminder tasks."""
    return {PENDING_REMINDER_TASKS_KEY: []}
