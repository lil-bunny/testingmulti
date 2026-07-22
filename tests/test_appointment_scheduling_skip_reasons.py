"""Tests for appointment scheduling skip reason → catalog mapping."""

from __future__ import annotations

from app.domain.appointment_scheduling.skip_reasons import (
    SKIP_APPOINTMENT_MODE_NOT_EMAIL,
    SKIP_APPOINTMENT_SHEET_UNREADABLE,
    SKIP_MISSING_APPOINTMENT_DATA_SOURCE,
    SKIP_MISSING_RECIPIENT_EMAIL,
    resolve_scheduling_error,
    scheduling_failure_from_skip,
)
from app.domain.error_catalog import BusinessError, IntegrationError


def test_resolve_missing_recipient_email() -> None:
    resolved = resolve_scheduling_error(
        SKIP_MISSING_RECIPIENT_EMAIL,
        customer_name="Costco",
    )
    assert resolved is not None
    catalog, message = resolved
    assert catalog == BusinessError.MISSING_RECIPIENT_EMAIL
    assert "Costco" in message


def test_resolve_ascend_not_configured() -> None:
    resolved = resolve_scheduling_error("ascend_not_configured")
    assert resolved is not None
    assert resolved[0] == BusinessError.ASCEND_NOT_CONFIGURED


def test_resolve_ascend_fetch_failed_legacy() -> None:
    resolved = resolve_scheduling_error(
        "ascend_fetch_failed",
        reference_number="REF-99",
        status_code="503",
    )
    assert resolved is not None
    assert resolved[0] == IntegrationError.ASCEND_SHIPMENT_FETCH_FAILED


def test_resolve_unknown_returns_none() -> None:
    assert resolve_scheduling_error("totally_unknown_reason") is None


def test_scheduling_failure_from_skip() -> None:
    failure = scheduling_failure_from_skip(
        SKIP_APPOINTMENT_SHEET_UNREADABLE,
    )
    assert failure is not None
    assert failure.code == BusinessError.APPOINTMENT_SHEET_UNREADABLE.value
    assert failure.category == BusinessError.CATEGORY


def test_all_recipient_gate_constants_resolve() -> None:
    for wire in (
        SKIP_MISSING_RECIPIENT_EMAIL,
        SKIP_MISSING_APPOINTMENT_DATA_SOURCE,
        SKIP_APPOINTMENT_SHEET_UNREADABLE,
        SKIP_APPOINTMENT_MODE_NOT_EMAIL,
    ):
        assert resolve_scheduling_error(wire, customer_name="X") is not None
