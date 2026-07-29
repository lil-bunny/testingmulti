"""Tests for app.core.asyncio_util.run_sync."""

from __future__ import annotations

import asyncio

import pytest

from app.core.asyncio_util import run_sync


async def _return_value(value: int) -> int:
    return value


def test_run_sync_runs_coroutine_when_no_loop() -> None:
    assert run_sync(_return_value(42)) == 42


@pytest.mark.asyncio
async def test_run_sync_refuses_nested_loop() -> None:
    coro = _return_value(1)
    try:
        with pytest.raises(RuntimeError, match="running event loop"):
            run_sync(coro)
    finally:
        coro.close()
