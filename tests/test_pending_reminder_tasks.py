"""Tests for pending reminder task metadata helpers."""

from __future__ import annotations

from app.domain.pending_reminder_tasks import (
    clear_pending_reminder_tasks,
    filter_pending_reminder_tasks,
    merge_pending_reminder_tasks,
    pending_reminder_tasks_from_metadata,
)


def test_merge_and_filter_pending_reminder_tasks() -> None:
    meta = merge_pending_reminder_tasks(
        {},
        new_entries=[{"task_id": "task-1", "attempt": 1}],
    )
    assert len(pending_reminder_tasks_from_metadata(meta)) == 1

    filtered = filter_pending_reminder_tasks(
        meta,
        remove_task_ids=frozenset({"task-1"}),
    )
    assert pending_reminder_tasks_from_metadata(filtered) == []

    cleared = clear_pending_reminder_tasks()
    assert pending_reminder_tasks_from_metadata(cleared) == []
