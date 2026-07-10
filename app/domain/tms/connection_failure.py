"""Detect normalized Turvo transport / transient HTTP exhaustion errors."""

from __future__ import annotations

_TMS_CONNECTION_TIMED_OUT_PHRASE = "tms connection timed out"


def is_tms_connection_timeout(exc: BaseException) -> bool:
    """True when ``TurvoApiClient`` exhausted transient retries."""
    from app.integrations.turvo.public_api_client import TurvoApiError

    if not isinstance(exc, TurvoApiError):
        return False
    if exc.status_code is not None:
        return False
    message = str(exc).strip().lower()
    return _TMS_CONNECTION_TIMED_OUT_PHRASE in message
