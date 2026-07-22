"""Lifecycle run queue Redis primitives (serialize-enqueue / start-next). No Celery publish."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.integrations.redis.client import get_redis_client

logger = get_logger(__name__)

SCOPE_LIFECYCLE = "lifecycle"


@dataclass(frozen=True)
class AdmitResult:
    """Outcome of RPUSH into a lifecycle run queue."""

    inbox_key: str
    length: int
    should_enqueue: bool


@dataclass(frozen=True)
class CompleteResult:
    """Outcome of atomic LPOP + LLEN after a Celery graph attempt."""

    inbox_key: str
    popped: dict[str, Any] | None
    remaining: int
    should_chain: bool


def lifecycle_run_queue_key(*, lifecycle_id: str) -> str:
    lid = str(lifecycle_id or "").strip()
    if not lid:
        raise ValueError("lifecycle_id required for lifecycle run queue")
    return f"inbox:{SCOPE_LIFECYCLE}:{lid}"


class LifecycleRunQueueService:
    """
    Redis FIFO keyed by one ``workflow_lifecycle_id``.

    Invariant: at most one in-flight graph Celery task per lifecycle; further
    Work items buffer on the list until start-next after complete.
    """

    def __init__(self, redis_client: Any | None = None) -> None:
        self._redis = redis_client

    def _client(self) -> Any:
        if self._redis is not None:
            return self._redis
        return get_redis_client()

    def admit(self, *, inbox_key: str, work_item: dict[str, Any]) -> AdmitResult:
        """
        Append one Work item (RPUSH).

        Outcomes: ``should_enqueue`` is True only when the list length becomes 1
        (publish-bridge may start Celery); otherwise the item is buffered.
        """
        key = str(inbox_key or "").strip()
        if not key:
            raise ValueError("inbox_key required for admit")

        redis = self._client()
        raw = json.dumps(work_item, default=str)
        length = int(redis.rpush(key, raw))
        should_enqueue = length == 1
        logger.info(
            "lifecycle_run_queue admit inbox_key=%s length=%s should_enqueue=%s",
            key,
            length,
            should_enqueue,
        )
        return AdmitResult(
            inbox_key=key,
            length=length,
            should_enqueue=should_enqueue,
        )

    def peek_head(self, *, inbox_key: str) -> dict[str, Any] | None:
        """
        Return the current head Work item without removing it.

        Corrupt or non-object heads are LPOP'd and skipped until a valid dict
        remains or the list is empty.
        """
        key = str(inbox_key or "").strip()
        if not key:
            raise ValueError("inbox_key required for peek_head")

        redis = self._client()
        while True:
            raw = redis.lindex(key, 0)
            if raw is None:
                return None
            try:
                item = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                logger.exception(
                    "lifecycle_run_queue corrupt_head inbox_key=%s; popping",
                    key,
                )
                redis.lpop(key)
                continue
            if not isinstance(item, dict):
                logger.error(
                    "lifecycle_run_queue non_object_head inbox_key=%s; popping",
                    key,
                )
                redis.lpop(key)
                continue
            return item

    def complete(self, *, inbox_key: str) -> CompleteResult:
        """
        Finish the current head Work item with MULTI LPOP + LLEN.

        Outcomes: ``should_chain`` is True when remaining length > 0 (caller may
        peek and publish the next graph start). Atomic so finish cannot race RPUSH.
        """
        key = str(inbox_key or "").strip()
        if not key:
            raise ValueError("inbox_key required for complete")

        redis = self._client()
        pipe = redis.pipeline(transaction=True)
        pipe.lpop(key)
        pipe.llen(key)
        popped_raw, remaining = pipe.execute()
        remaining_n = int(remaining or 0)

        popped: dict[str, Any] | None = None
        if popped_raw is not None:
            try:
                parsed = json.loads(popped_raw)
                if isinstance(parsed, dict):
                    popped = parsed
            except (TypeError, json.JSONDecodeError):
                logger.exception(
                    "lifecycle_run_queue corrupt_popped inbox_key=%s",
                    key,
                )

        should_chain = remaining_n > 0
        logger.info(
            "lifecycle_run_queue complete inbox_key=%s remaining=%s should_chain=%s",
            key,
            remaining_n,
            should_chain,
        )
        return CompleteResult(
            inbox_key=key,
            popped=popped,
            remaining=remaining_n,
            should_chain=should_chain,
        )

