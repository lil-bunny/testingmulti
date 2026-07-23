"""Tests for AppointmentSchedulingTurvoStopUpdateService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.appointment_scheduling.turvo_stop_update_service import (
    AppointmentSchedulingTurvoStopUpdateService,
)


def _shipment_payload(*, route_stop: str = "Delivery WH", delivery_date: str = "2026-07-18") -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Costco"},
                    "items": [{"deliveryLocation": [{"name": route_stop}]}],
                }
            ],
            "globalRoute": [
                {
                    "deleted": False,
                    "id": 202,
                    "name": route_stop,
                    "appointment": {"date": delivery_date},
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_apply_delivery_placeholder_sets_0001() -> None:
    svc = AppointmentSchedulingTurvoStopUpdateService()
    payload = _shipment_payload()
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})

    with patch(
        "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
        new=mock_update,
    ):
        result = await svc.apply_delivery_placeholder(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            shipment_payload=payload,
        )

    assert result.ok is True
    assert result.start_time == "2026-07-18 00:01:00"
    assert result.stop_name == "Delivery WH"
    mock_update.assert_awaited_once()
    assert mock_update.await_args.kwargs["start_time"] == "2026-07-18 00:01:00"


@pytest.mark.asyncio
async def test_apply_delivery_placeholder_missing_shipment_fields() -> None:
    svc = AppointmentSchedulingTurvoStopUpdateService()
    result = await svc.apply_delivery_placeholder(
        tenant_slug="",
        shipment_id="",
    )
    assert result.ok is False
    assert result.error == "missing_turvo_shipment_fields"
