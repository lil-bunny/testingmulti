"""Tests for TMS connection timeout detection."""

from __future__ import annotations

from app.domain.tms.connection_failure import is_tms_connection_timeout
from app.integrations.turvo.public_api_client import TurvoApiError


def test_is_tms_connection_timeout_true_on_exhaustion() -> None:
    exc = TurvoApiError("TMS connection timed out after 5 attempts", status_code=None)
    assert is_tms_connection_timeout(exc) is True


def test_is_tms_connection_timeout_false_on_404() -> None:
    exc = TurvoApiError("Turvo GET /shipments/1 returned 404", status_code=404)
    assert is_tms_connection_timeout(exc) is False


def test_is_tms_connection_timeout_false_on_generic_error() -> None:
    assert is_tms_connection_timeout(RuntimeError("boom")) is False
