"""Blocking wait with a live terminal countdown (for long async e2e steps)."""

from __future__ import annotations

import sys
import time
from typing import TextIO


def wait_with_countdown(
    *,
    total_s: int,
    label: str = "",
    stream: TextIO | None = None,
) -> None:
    """Sleep for ``total_s`` seconds, printing remaining MM:SS on ``stream`` each second.

    Uses ``\\r`` so one line updates in place. Call under ``capsys.disabled()`` in pytest
    so output is not buffered until the test ends.
    """
    stream = stream or sys.stderr
    deadline = time.monotonic() + float(total_s)
    prefix = f"[{label}] " if label else ""
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            stream.write(f"\r{prefix}Countdown 00:00 — done\n")
            stream.flush()
            return
        whole = int(remaining)
        mins, secs = divmod(whole, 60)
        stream.write(f"\r{prefix}Countdown {mins:02d}:{secs:02d} remaining until DB snapshot")
        stream.flush()
        time.sleep(min(1.0, remaining))
