"""Tests for AppointmentSchedulingTurvoWriteService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.appointment_scheduling.turvo_write_service import (
    AppointmentSchedulingTurvoWriteService,
)
from app.services.shipments_service import ShipmentsService


def _shipment_payload(*, route_stop: str = "Costco Depot") -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Costco Wholesale"},
                    "items": [{"deliveryLocation": [{"name": route_stop}]}],
                }
            ],
            "globalRoute": [
                {"deleted": False, "id": 202, "name": route_stop, "appointment": {}},
            ],
        }
    }


@pytest.mark.asyncio
async def test_apply_delivery_success() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    with patch(
        "app.services.appointment_scheduling.turvo_write_service.update_stop_appointment_time",
        new=AsyncMock(
            return_value={
                "ok": True,
                "updated": True,
                "stop_name": "Costco",
                "start_time": "2026-07-18 10:30:00",
            }
        ),
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            stop_name="Costco",
            start_time="2026-07-18 10:30:00",
        )

    assert result.ok is True
    assert result.updated is True
    assert result.stop_name == "Costco"


@pytest.mark.asyncio
async def test_apply_delivery_missing_fields() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    result = await svc.apply_delivery(
        tenant_slug="",
        shipment_id="1001",
        stop_name="Costco",
        start_time="",
    )
    assert result.ok is False
    assert result.error == "missing_turvo_update_fields"


@pytest.mark.asyncio
async def test_apply_delivery_resolves_stop_name_from_shipment_payload() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    payload = _shipment_payload(route_stop="Costco Depot SC")
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})

    with patch(
        "app.services.appointment_scheduling.turvo_write_service.update_stop_appointment_time",
        new=mock_update,
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            start_time="2026-07-18 10:30:00",
            shipment_payload=payload,
        )

    assert result.ok is True
    assert result.stop_name == "Costco Depot SC"
    mock_update.assert_awaited_once()
    assert mock_update.await_args.kwargs["stop_name"] == "Costco Depot SC"
    assert mock_update.await_args.kwargs["shipment_payload"] is payload


@pytest.mark.asyncio
async def test_apply_delivery_from_state_ignores_customer_name_column() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    payload = _shipment_payload(route_stop="Delivery WH")
    state = SimpleNamespace(
        data={
            "tenant_slug": "t3ra",
            "shipment_id": "1000324895",
            "customer_name": "Costco Wholesale",
            "customer_reply_extraction": {"turvo_start_time": "2026-07-18 10:30:00"},
            "shipment": payload,
        }
    )
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})

    with patch(
        "app.services.appointment_scheduling.turvo_write_service.update_stop_appointment_time",
        new=mock_update,
    ):
        result = await svc.apply_delivery_from_state(state)

    assert result.ok is True
    assert result.stop_name == "Delivery WH"
    assert mock_update.await_args.kwargs["stop_name"] == "Delivery WH"


@pytest.mark.asyncio
async def test_apply_delivery_refreshes_shipment_display_when_ids_present() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})
    mock_refresh = AsyncMock(return_value={"success": True})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_write_service.update_stop_appointment_time",
            new=mock_update,
        ),
        patch.object(ShipmentsService, "refresh_display_from_turvo", new=mock_refresh),
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            stop_name="Costco",
            start_time="2026-07-18 10:30:00",
            tenant_id="00000000-0000-4000-8000-0000000000e1",
            load_id="30381",
        )

    assert result.ok is True
    mock_refresh.assert_awaited_once_with(
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        tenant_slug="t3ra",
        turvo_shipment_id="1000324895",
        load_id="30381",
    )


@pytest.mark.asyncio
async def test_apply_delivery_still_ok_when_display_refresh_fails() -> None:
    svc = AppointmentSchedulingTurvoWriteService()
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})
    mock_refresh = AsyncMock(return_value={"success": False, "message": "turvo_get_shipment_failed"})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_write_service.update_stop_appointment_time",
            new=mock_update,
        ),
        patch.object(ShipmentsService, "refresh_display_from_turvo", new=mock_refresh),
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            stop_name="Costco",
            start_time="2026-07-18 10:30:00",
            tenant_id="00000000-0000-4000-8000-0000000000e1",
            load_id="30381",
        )

    assert result.ok is True
    mock_refresh.assert_awaited_once()
