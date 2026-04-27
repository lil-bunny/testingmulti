"""HTTP calls to Turvo Public API OAuth token endpoint."""

from __future__ import annotations

from typing import Any, Optional

import httpx

from app.core.logger import get_logger

logger = get_logger(__name__)


class TurvoOAuthHttpError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None, body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


async def post_token(
    token_url: str,
    json_body: dict[str, Any],
    x_api_key: Optional[str],
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if x_api_key:
        headers["x-api-key"] = x_api_key

    async with httpx.AsyncClient(timeout=timeout_s) as client:
        resp = await client.post(token_url, headers=headers, json=json_body)

    if resp.status_code != 200:
        logger.warning(
            "Turvo token HTTP %s: %s",
            resp.status_code,
            resp.text[:500] if resp.text else "",
        )
        raise TurvoOAuthHttpError(
            f"Turvo token endpoint returned {resp.status_code}",
            status_code=resp.status_code,
            body=resp.text,
        )

    try:
        data = resp.json()
    except Exception as e:
        raise TurvoOAuthHttpError("Turvo token response is not valid JSON", body=resp.text) from e

    if "access_token" not in data:
        raise TurvoOAuthHttpError("Turvo token JSON missing access_token", body=resp.text)

    return data
