"""Tests for Ascend error → catalog mapping."""

from __future__ import annotations

import httpx

from app.domain.error_catalog import IntegrationError, format_error_message
from app.integrations.ascend.error_mapping import (
    catalog_from_ascend_api_error,
    is_ascend_timeout,
)
from app.integrations.ascend.errors import AscendApiError


def test_catalog_from_ascend_api_error_login() -> None:
    exc = AscendApiError("Ascend login failed", status_code=401)
    catalog, message = catalog_from_ascend_api_error(exc, operation="login")
    assert catalog == IntegrationError.ASCEND_LOGIN_FAILED
    assert "401" in message


def test_catalog_from_ascend_api_error_shipment_fetch() -> None:
    exc = AscendApiError("fetch failed", status_code=404)
    catalog, message = catalog_from_ascend_api_error(
        exc,
        operation="shipment_fetch",
        reference_number="DIAMOND-RPN001",
    )
    assert catalog == IntegrationError.ASCEND_SHIPMENT_FETCH_FAILED
    assert "DIAMOND-RPN001" in message
    assert "404" in message


def test_catalog_from_ascend_api_error_dropoff_update() -> None:
    exc = AscendApiError("update failed", status_code=500)
    catalog, _ = catalog_from_ascend_api_error(
        exc,
        operation="dropoff_update",
        reference_number="REF-1",
    )
    assert catalog == IntegrationError.ASCEND_DROPOFF_UPDATE_FAILED


def test_is_ascend_timeout_httpx() -> None:
    assert is_ascend_timeout(httpx.ReadTimeout("timed out")) is True


def test_is_ascend_timeout_maps_to_vendor_api_timeout() -> None:
    exc = AscendApiError("request timed out")
    catalog, message = catalog_from_ascend_api_error(exc, operation="login")
    assert catalog == IntegrationError.VENDOR_API_TIMEOUT
    assert message == format_error_message(IntegrationError.VENDOR_API_TIMEOUT)
