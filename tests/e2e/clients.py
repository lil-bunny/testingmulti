"""HTTP helpers for E2E webhook calls."""

from __future__ import annotations

import httpx


def post_json(
    *,
    base_url: str,
    path: str,
    json_body: dict,
    headers: dict[str, str] | None = None,
    timeout: float | httpx.Timeout | None = None,
) -> httpx.Response:
    """POST JSON to the API. ``timeout=None`` (default) waits until the server responds (no client cap)."""
    url = base_url.rstrip("/") + path
    return httpx.post(url, json=json_body, headers=headers or {}, timeout=timeout)
