"""Tests for local AscendError enum and SchedulingFailure.from_ascend."""

from __future__ import annotations

import httpx

from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.error_catalog import ErrorCategory, IntegrationError, format_error_message
from app.integrations.ascend.errors import AscendApiError, AscendError, is_ascend_timeout, resolve_ascend_error


def test_from_ascend_login_failed() -> None:
    failure = SchedulingFailure.from_ascend(
        AscendError.LOGIN_FAILED,
        status_code="401",
    )
    assert failure.code == "ascend_login_failed"
    assert failure.category == ErrorCategory.INTEGRATION
    assert "401" in failure.message


def test_from_ascend_shipment_fetch_failed() -> None:
    failure = SchedulingFailure.from_ascend(
        AscendError.SHIPMENT_FETCH_FAILED,
        reference_number="DIAMOND-RPN001",
        status_code="404",
    )
    assert failure.code == "ascend_shipment_fetch_failed"
    assert "DIAMOND-RPN001" in failure.message
    assert "404" in failure.message


def test_resolve_ascend_error() -> None:
    assert resolve_ascend_error("ascend_dropoff_update_failed") == AscendError.DROPOFF_UPDATE_FAILED
    assert resolve_ascend_error("unknown") is None


def test_from_wire_resolves_ascend_code() -> None:
    failure = SchedulingFailure.from_wire("ascend_login_failed", "custom")
    assert failure.code == "ascend_login_failed"
    assert failure.category == ErrorCategory.INTEGRATION
    assert failure.message == "custom"


def test_is_ascend_timeout_httpx() -> None:
    assert is_ascend_timeout(httpx.ReadTimeout("timed out")) is True


def test_is_ascend_timeout_ascend_api_error() -> None:
    assert is_ascend_timeout(AscendApiError("request timed out")) is True


def test_timeout_uses_global_vendor_api_timeout() -> None:
    failure = SchedulingFailure.from_catalog(IntegrationError.VENDOR_API_TIMEOUT)
    assert failure.code == IntegrationError.VENDOR_API_TIMEOUT.value
    assert failure.message == format_error_message(IntegrationError.VENDOR_API_TIMEOUT)
