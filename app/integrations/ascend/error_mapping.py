"""Map Ascend API failures to workflow error catalog entries."""

from __future__ import annotations

import httpx

from app.domain.error_catalog import IntegrationError, format_error_message
from app.integrations.ascend.errors import AscendApiError

_ASCEND_OPERATIONS = frozenset(
    {
        "login",
        "shipment_fetch",
        "availability_fetch",
        "pickup_update",
        "dropoff_update",
    }
)

_OPERATION_TO_ERROR: dict[str, IntegrationError] = {
    "login": IntegrationError.ASCEND_LOGIN_FAILED,
    "shipment_fetch": IntegrationError.ASCEND_SHIPMENT_FETCH_FAILED,
    "availability_fetch": IntegrationError.ASCEND_AVAILABILITY_FETCH_FAILED,
    "pickup_update": IntegrationError.ASCEND_PICKUP_UPDATE_FAILED,
    "dropoff_update": IntegrationError.ASCEND_DROPOFF_UPDATE_FAILED,
}


def is_ascend_timeout(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, AscendApiError):
        msg = str(exc).lower()
        return "timeout" in msg or "timed out" in msg
    return False


def catalog_from_ascend_api_error(
    exc: AscendApiError,
    *,
    operation: str,
    reference_number: str = "",
) -> tuple[IntegrationError, str]:
    op = operation if operation in _ASCEND_OPERATIONS else "shipment_fetch"
    if is_ascend_timeout(exc):
        message = format_error_message(IntegrationError.VENDOR_API_TIMEOUT)
        return IntegrationError.VENDOR_API_TIMEOUT, message

    catalog = _OPERATION_TO_ERROR.get(op, IntegrationError.ASCEND_SHIPMENT_FETCH_FAILED)
    status = str(exc.status_code or "")
    ref = str(reference_number or "").strip()
    if catalog == IntegrationError.ASCEND_LOGIN_FAILED:
        message = format_error_message(catalog, status_code=status)
    elif catalog == IntegrationError.ASCEND_AVAILABILITY_FETCH_FAILED:
        message = format_error_message(catalog, reference_number=ref)
    else:
        message = format_error_message(
            catalog,
            reference_number=ref,
            status_code=status,
        )
    return catalog, message
