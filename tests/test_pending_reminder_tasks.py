"""Tests for pending reminder task metadata helpers."""

from __future__ import annotations

from app.domain.pending_reminder_tasks import (
    PENDING_REMINDER_TASKS_KEY,
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
def test_pending_reminder_tasks_from_metadata_empty():
    assert pending_reminder_tasks_from_metadata(None) == []
    assert pending_reminder_tasks_from_metadata({}) == []
    assert pending_reminder_tasks_from_metadata({PENDING_REMINDER_TASKS_KEY: "x"}) == []


def test_pending_reminder_tasks_from_metadata_skips_invalid_rows():
    meta = {
        PENDING_REMINDER_TASKS_KEY: [
            {"task_id": "t1", "event_type": "reminder_due", "step": 1},
            {"task_id": ""},
            "bad",
            {"event_type": "reminder_due"},
        ]
    }
    out = pending_reminder_tasks_from_metadata(meta)
    assert len(out) == 1
    assert out[0]["task_id"] == "t1"


def test_merge_pending_reminder_tasks():
    meta = {PENDING_REMINDER_TASKS_KEY: [{"task_id": "t1"}]}
    patch = merge_pending_reminder_tasks(
        meta,
        new_entries=[{"task_id": "t2", "step": 2}],
    )
    assert patch[PENDING_REMINDER_TASKS_KEY] == [
        {"task_id": "t1"},
        {"task_id": "t2", "step": 2},
    ]


def test_filter_pending_reminder_tasks():
    meta = {
        PENDING_REMINDER_TASKS_KEY: [
            {"task_id": "t1"},
            {"task_id": "t2"},
        ]
    }
    patch = filter_pending_reminder_tasks(meta, remove_task_ids=frozenset({"t1"}))
    assert patch[PENDING_REMINDER_TASKS_KEY] == [{"task_id": "t2"}]


def test_clear_pending_reminder_tasks():
    assert clear_pending_reminder_tasks() == {PENDING_REMINDER_TASKS_KEY: []}
