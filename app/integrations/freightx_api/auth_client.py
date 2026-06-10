"""Validate portal Bearer tokens via freightx-api ``GET /api/v1/auth/me``."""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logger import get_logger
from app.domain.api_user import ApiUser
from app.domain.auth_errors import AuthServiceUnavailableError, AuthUnauthorizedError

logger = get_logger(__name__)


async def validate_token(token: str) -> ApiUser:
    """GET {FREIGHTX_API_BASE_URL}/api/v1/auth/me with Bearer token."""
    base = settings.FREIGHTX_API_BASE_URL.rstrip("/")
    url = f"{base}/api/v1/auth/me"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=settings.FREIGHTX_API_TIMEOUT_S) as client:
            response = await client.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        logger.warning("freightx-api /auth/me timeout url=%s", url)
        raise AuthServiceUnavailableError("Authentication service timed out") from exc
    except httpx.RequestError as exc:
        logger.warning("freightx-api /auth/me request failed url=%s err=%s", url, exc)
        raise AuthServiceUnavailableError("Authentication service unavailable") from exc

    if response.status_code == 401:
        raise AuthUnauthorizedError("Invalid or expired token")
    if response.status_code >= 500:
        raise AuthServiceUnavailableError(
            f"Authentication service error (HTTP {response.status_code})"
        )
    if response.status_code != 200:
        logger.warning(
            "freightx-api /auth/me unexpected status=%s body=%r",
            response.status_code,
            response.text[:500],
        )
        raise AuthUnauthorizedError("Invalid or expired token")

    return ApiUser.model_validate(response.json())
