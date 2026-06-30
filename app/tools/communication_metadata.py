"""Helpers for linking graph state to ``communications`` / ``activity_logs``."""

from __future__ import annotations

from typing import Any


def stash_communication_id(state: Any, send_result: dict[str, Any] | None) -> str | None:
    """Copy ``communication_id`` from a send result onto ``state.data``."""
    if not isinstance(send_result, dict):
        return None
    comm_id = send_result.get("communication_id")
    if not comm_id:
        return None
    cid = str(comm_id).strip()
    if not cid:
        return None
    data = getattr(state, "data", None)
    if isinstance(data, dict):
        data["communication_id"] = cid
    return cid
