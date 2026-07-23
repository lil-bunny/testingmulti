"""Loop-safe sync bridge for calling async code from sync graph nodes / Celery workers."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import TypeVar

_T = TypeVar("_T")


def run_sync(coro: Coroutine[object, object, _T]) -> _T:
    """Run ``coro`` when no event loop is running; refuse nested ``asyncio.run``."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    raise RuntimeError(
        "run_sync cannot be called under a running event loop; use the async API"
    )


__all__ = ("run_sync",)
