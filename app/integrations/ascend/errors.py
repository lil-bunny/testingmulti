from __future__ import annotations

from enum import Enum

import httpx

from app.domain.error_catalog import ErrorCategory


class AscendApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class AscendError(Enum):
    """Ascend HTTP failures — local to this integration (not global error_catalog)."""

    LOGIN_FAILED = (
        "ascend_login_failed",
        "Ascend login failed (HTTP {status_code}).",
    )
    SHIPMENT_FETCH_FAILED = (
        "ascend_shipment_fetch_failed",
        "Ascend shipment fetch failed for {reference_number} (HTTP {status_code}).",
    )
    AVAILABILITY_FETCH_FAILED = (
        "ascend_availability_fetch_failed",
        "Ascend warehouse availability fetch failed for {reference_number}.",
    )
    PICKUP_UPDATE_FAILED = (
        "ascend_pickup_update_failed",
        "Ascend pickup appointment update failed for {reference_number}.",
    )
    DROPOFF_UPDATE_FAILED = (
        "ascend_dropoff_update_failed",
        "Ascend dropoff appointment update failed for {reference_number}.",
    )

    def __new__(cls, *values: str | tuple[str, str]):
        if len(values) == 1 and isinstance(values[0], tuple):
            code, description = values[0]
        elif len(values) == 2:
            code, description = values
        else:
            raise TypeError(f"Invalid AscendError values: {values!r}")

        obj = object.__new__(cls)
        obj._value_ = code
        obj.description = description
        return obj

    @property
    def category(self) -> ErrorCategory:
        return ErrorCategory.INTEGRATION


_ASCEND_ERROR_BY_CODE: dict[str, AscendError] = {member.value: member for member in AscendError}


def resolve_ascend_error(code: str) -> AscendError | None:
    return _ASCEND_ERROR_BY_CODE.get(str(code or "").strip())


def is_ascend_timeout(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, AscendApiError):
        msg = str(exc).lower()
        return "timeout" in msg or "timed out" in msg
    return False
