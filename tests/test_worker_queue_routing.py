"""Unit tests for Celery work-queue routing helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.config import settings
from app.services.worker_queue_routing import (
    apply_async_on_work_queue,
    resolve_work_queue,
)


def test_resolve_work_queue_t3ra() -> None:
    assert resolve_work_queue("t3ra") == settings.T3RA_WORK_QUEUE
    assert resolve_work_queue("  t3ra  ") == settings.T3RA_WORK_QUEUE


def test_resolve_work_queue_other_tenants_default() -> None:
    assert resolve_work_queue("gelita") == settings.DEFAULT_WORK_QUEUE
    assert resolve_work_queue("unknown") == settings.DEFAULT_WORK_QUEUE


def test_resolve_work_queue_unguarded_blank(caplog) -> None:
    with caplog.at_level("WARNING"):
        assert resolve_work_queue(None) == settings.DEFAULT_WORK_QUEUE
        assert resolve_work_queue("") == settings.DEFAULT_WORK_QUEUE
        assert resolve_work_queue("   ") == settings.DEFAULT_WORK_QUEUE
    assert any("unguarded enqueue" in r.message for r in caplog.records)


def test_apply_async_on_work_queue_sets_queue_and_forwards_kwargs() -> None:
    task = MagicMock()
    task.apply_async.return_value = MagicMock(id="task-1")

    result = apply_async_on_work_queue(
        task,
        tenant_slug="t3ra",
        kwargs={"payload": {"x": 1}},
        countdown=60,
        task_id="fixed-id",
    )

    assert result.id == "task-1"
    task.apply_async.assert_called_once_with(
        kwargs={"payload": {"x": 1}},
        countdown=60,
        task_id="fixed-id",
        queue=settings.T3RA_WORK_QUEUE,
    )


def test_apply_async_on_work_queue_gelita_uses_default() -> None:
    task = MagicMock()
    apply_async_on_work_queue(task, tenant_slug="gelita", kwargs={})
    assert task.apply_async.call_args.kwargs["queue"] == settings.DEFAULT_WORK_QUEUE
