"""Ascend auth — POST /auth/user/login."""

from __future__ import annotations

from typing import Any

import httpx

from app.integrations.ascend.errors import AscendApiError

_BASE_URL = "https://api.ascendcargo.com"
_DEFAULT_TIMEOUT_S = 60.0


def login_ascend_api(
    *,
    email: str,
    password: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    if not email or not password:
        raise AscendApiError("Ascend credentials missing")
    try:
        response = httpx.post(
            f"{_BASE_URL}/auth/user/login",
            json={"email": email, "password": password},
            timeout=timeout_s,
        )
    except httpx.HTTPError as exc:
        raise AscendApiError(f"Ascend login request failed: {exc}") from exc
    if response.status_code >= 400:
        raise AscendApiError(
            "Ascend login failed",
            status_code=response.status_code,
            body=response.text,
        )
    data = response.json()
    if not isinstance(data, dict) or not data.get("accessToken"):
        raise AscendApiError("Ascend login response missing accessToken")
    return data
