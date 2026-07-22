"""Unit tests for lifecycle run queue (MULTI complete / admit)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.services.lifecycle_run_queue_service import (
    LifecycleRunQueueService,
    lifecycle_run_queue_key,
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


def test_lifecycle_run_queue_key() -> None:
    assert lifecycle_run_queue_key(lifecycle_id="abc") == "inbox:lifecycle:abc"


def test_admit_empty_should_enqueue() -> None:
    redis = _FakeRedis()
    svc = LifecycleRunQueueService(redis_client=redis)
    key = lifecycle_run_queue_key(lifecycle_id="lc-1")
    result = svc.admit(inbox_key=key, work_item={"n": 1})
    assert result.should_enqueue is True
    assert result.length == 1


def test_admit_nonempty_buffers() -> None:
    redis = _FakeRedis()
    svc = LifecycleRunQueueService(redis_client=redis)
    key = lifecycle_run_queue_key(lifecycle_id="lc-1")
    svc.admit(inbox_key=key, work_item={"n": 1})
    second = svc.admit(inbox_key=key, work_item={"n": 2})
    assert second.should_enqueue is False
    assert second.length == 2


def test_complete_transaction_remaining() -> None:
    redis = _FakeRedis()
    svc = LifecycleRunQueueService(redis_client=redis)
    key = lifecycle_run_queue_key(lifecycle_id="lc-1")
    svc.admit(inbox_key=key, work_item={"n": 1})
    svc.admit(inbox_key=key, work_item={"n": 2})
    done = svc.complete(inbox_key=key)
    assert done.should_chain is True
    assert done.remaining == 1
    assert done.popped == {"n": 1}
    head = svc.peek_head(inbox_key=key)
    assert head == {"n": 2}


def test_complete_drains() -> None:
    redis = _FakeRedis()
    svc = LifecycleRunQueueService(redis_client=redis)
    key = lifecycle_run_queue_key(lifecycle_id="lc-1")
    svc.admit(inbox_key=key, work_item={"n": 1})
    done = svc.complete(inbox_key=key)
    assert done.should_chain is False
    assert done.remaining == 0


def test_peek_pops_corrupt_head() -> None:
    redis = _FakeRedis()
    key = lifecycle_run_queue_key(lifecycle_id="lc-1")
    redis.lists[key] = ["not-json", json.dumps({"ok": True})]
    svc = LifecycleRunQueueService(redis_client=redis)
    head = svc.peek_head(inbox_key=key)
    assert head == {"ok": True}
