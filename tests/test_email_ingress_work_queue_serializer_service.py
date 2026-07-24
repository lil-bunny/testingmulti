"""Unit tests for the Pre-Lifecycle Work Queue publish-bridge (email_id scope)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from app.services.email_ingress_work_queue_serializer_service import (
    EmailIngressWorkQueueSerializerService,
)
from app.services.lifecycle_run_queue_service import (
    LifecycleRunQueueService,
    email_ingress_work_queue_key,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}

    def rpush(self, key: str, value: str) -> int:
        self.lists.setdefault(key, []).append(value)
        return len(self.lists[key])

    def lindex(self, key: str, index: int) -> str | None:
        items = self.lists.get(key) or []
        if index < 0 or index >= len(items):
            return None
        return items[index]

    def lpop(self, key: str) -> str | None:
        items = self.lists.get(key) or []
        if not items:
            return None
        return items.pop(0)

    def llen(self, key: str) -> int:
        return len(self.lists.get(key) or [])

    def pipeline(self, transaction: bool = False) -> "_FakePipe":
        return _FakePipe(self)


class _FakePipe:
    def __init__(self, redis: _FakeRedis) -> None:
        self._redis = redis
        self._ops: list[tuple[str, tuple[Any, ...]]] = []

    def lpop(self, key: str) -> None:
        self._ops.append(("lpop", (key,)))

    def llen(self, key: str) -> None:
        self._ops.append(("llen", (key,)))

    def execute(self) -> list[Any]:
        out: list[Any] = []
        for op, args in self._ops:
            if op == "lpop":
                out.append(self._redis.lpop(args[0]))
            elif op == "llen":
                out.append(self._redis.llen(args[0]))
        self._ops.clear()
        return out


def _service(redis: _FakeRedis) -> EmailIngressWorkQueueSerializerService:
    queue = LifecycleRunQueueService(redis_client=redis)
    return EmailIngressWorkQueueSerializerService(run_queue=queue)


def test_admit_first_delivery_publishes() -> None:
    redis = _FakeRedis()
    service = _service(redis)
    with patch("app.tasks.email.run_email_webhook") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-1")
        result = service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1"},
        )

    assert result.status == "started"
    assert result.celery_task_id == "task-1"
    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["handler"] == "inbound.unipile_email"
    assert call_kwargs["email_id"] == "mail-1"
    assert call_kwargs["tenant_slug"] == "gelita"


def test_admit_duplicate_delivery_buffers_without_publish() -> None:
    redis = _FakeRedis()
    service = _service(redis)
    with patch("app.tasks.email.run_email_webhook") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-1")
        service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1"},
        )
        mock_task.apply_async.reset_mock()

        second = service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1", "retry": True},
        )

    assert second.status == "buffered"
    assert second.length == 2
    mock_task.apply_async.assert_not_called()


def test_complete_and_start_next_drains_when_empty() -> None:
    redis = _FakeRedis()
    service = _service(redis)
    with patch("app.tasks.email.run_email_webhook") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-1")
        service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1"},
        )
        mock_task.apply_async.reset_mock()

        result = service.complete_and_start_next(email_id="mail-1")

    assert result is None
    key = email_ingress_work_queue_key(email_id="mail-1")
    assert redis.llen(key) == 0
    mock_task.apply_async.assert_not_called()


def test_complete_and_start_next_publishes_buffered_item() -> None:
    redis = _FakeRedis()
    service = _service(redis)
    with patch("app.tasks.email.run_email_webhook") as mock_task:
        mock_task.apply_async.return_value = MagicMock(id="task-1")
        service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1"},
        )
        service.admit(
            email_id="mail-1",
            tenant_uuid="tenant-1",
            tenant_slug="gelita",
            payload={"email_id": "mail-1", "retry": True},
        )
        mock_task.apply_async.reset_mock()

        result = service.complete_and_start_next(email_id="mail-1")

    assert result is not None
    assert result.status == "started"
    mock_task.apply_async.assert_called_once()
    call_kwargs = mock_task.apply_async.call_args.kwargs["kwargs"]
    assert call_kwargs["payload"] == {"email_id": "mail-1", "retry": True}
