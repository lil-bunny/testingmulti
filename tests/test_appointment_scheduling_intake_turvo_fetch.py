"""Tests for appointment scheduling intake Turvo fetch failure handling."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.domain.error_catalog import IntegrationError
from app.integrations.turvo.public_api_client import TurvoApiError
from app.services.appointment_scheduling.intake_service import IntakeService


def test_run_intake_turvo_fetch_failure_returns_catalog_failure() -> None:
    service = IntakeService()
    with patch.object(
        service,
        "_turvo_shipment_from_payload",
        new=AsyncMock(side_effect=TurvoApiError("fetch failed", status_code=503)),
    ):
        result = service.run_intake(
            tenant_slug="t3ra",
            tenant_settings={"appointment_scheduling": {}},
            payload={"shipment_id": "SHP-1"},
        )

    assert result.ok is False
    assert result.failure is not None
    assert result.failure.code == IntegrationError.TURVO_SHIPMENT_FETCH_FAILED.value
    assert result.failure.category == IntegrationError.CATEGORY
