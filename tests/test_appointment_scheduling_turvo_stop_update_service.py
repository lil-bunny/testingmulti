"""Tests for TurvoStopUpdateService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.appointment_scheduling.turvo_stop_update_service import (
    TurvoStopUpdateService,
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
    svc = TurvoStopUpdateService()
    with patch(
        "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
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
    svc = TurvoStopUpdateService()
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
    svc = TurvoStopUpdateService()
    payload = _shipment_payload(route_stop="Costco Depot SC")
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})

    with patch(
        "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
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
    svc = TurvoStopUpdateService()
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
        "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
        new=mock_update,
    ):
        result = await svc._apply_delivery_from_state_async(state)

    assert result.ok is True
    assert result.stop_name == "Delivery WH"
    assert mock_update.await_args.kwargs["stop_name"] == "Delivery WH"


@pytest.mark.asyncio
async def test_apply_delivery_refreshes_shipment_display_when_ids_present() -> None:
    svc = TurvoStopUpdateService()
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})
    mock_refresh = AsyncMock(return_value={"success": True})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
            new=mock_update,
        ),
        patch.object(ShipmentsService, "refresh_display_from_turvo", new=mock_refresh),
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            stop_name="Costco",
            start_time="2026-07-18 10:30:00",
            shipment_payload={},
            tenant_id="00000000-0000-4000-8000-0000000000e1",
            load_id="30381",
        )

    assert result.ok is True
    mock_refresh.assert_awaited_once_with(
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        tenant_slug="t3ra",
        turvo_shipment_id="1000324895",
        load_id="30381",
        customer_name_override=None,
    )


@pytest.mark.asyncio
async def test_apply_delivery_refresh_passes_customer_name_override_from_payload() -> None:
    svc = TurvoStopUpdateService()
    payload = _shipment_payload(route_stop="PETCO DC 810")
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})
    mock_refresh = AsyncMock(return_value={"success": True})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
            new=mock_update,
        ),
        patch.object(ShipmentsService, "refresh_display_from_turvo", new=mock_refresh),
    ):
        result = await svc.apply_delivery(
            tenant_slug="t3ra",
            shipment_id="1000324895",
            start_time="2026-07-18 10:30:00",
            shipment_payload=payload,
            tenant_id="00000000-0000-4000-8000-0000000000e1",
            load_id="30381",
        )

    assert result.ok is True
    mock_refresh.assert_awaited_once_with(
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        tenant_slug="t3ra",
        turvo_shipment_id="1000324895",
        load_id="30381",
        customer_name_override="PETCO DC 810",
    )


@pytest.mark.asyncio
async def test_apply_delivery_still_ok_when_display_refresh_fails() -> None:
    svc = TurvoStopUpdateService()
    mock_update = AsyncMock(return_value={"ok": True, "updated": True})
    mock_refresh = AsyncMock(return_value={"success": False, "message": "turvo_get_shipment_failed"})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_stop_appointment_time",
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


def _tender_app_payload(*, status_key: str = "2118", fragment_id: str = "frag-uuid") -> dict:
    return {
        "details": {
            "status": {"code": {"key": status_key, "value": "Tender - accepted"}},
            "global_route": {"fragments": [{"fragment_id": fragment_id}]},
            "globalRoute": [
                {"appointment": {"timeZone": "America/Los_Angeles"}},
            ],
        }
    }


@pytest.mark.asyncio
async def test_apply_tender_success() -> None:
    svc = TurvoStopUpdateService()
    payload = _tender_app_payload()
    mock_fetch = AsyncMock(return_value=payload)
    mock_put = AsyncMock(return_value={"respMsg": "SUCCESS_UPDATE"})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.fetch_app_shipment_details",
            new=mock_fetch,
        ),
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_shipment_tender_status",
            new=mock_put,
        ),
    ):
        result = await svc.apply_tender(tenant_slug="t3ra", shipment_id="1000324213")

    assert result.ok is True
    assert result.updated is True
    assert result.skipped is False
    mock_put.assert_awaited_once()
    assert mock_put.await_args.args[2]["fragment_id"] == "frag-uuid"


@pytest.mark.asyncio
async def test_apply_tender_refresh_passes_customer_name_override() -> None:
    svc = TurvoStopUpdateService()
    payload = _tender_app_payload()
    mock_fetch = AsyncMock(return_value=payload)
    mock_put = AsyncMock(return_value={"respMsg": "SUCCESS_UPDATE"})
    mock_refresh = AsyncMock(return_value={"success": True})

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.fetch_app_shipment_details",
            new=mock_fetch,
        ),
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_shipment_tender_status",
            new=mock_put,
        ),
        patch.object(ShipmentsService, "refresh_display_from_turvo", new=mock_refresh),
    ):
        result = await svc.apply_tender(
            tenant_slug="t3ra",
            shipment_id="1000324213",
            tenant_id="00000000-0000-4000-8000-0000000000e1",
            load_id="30381",
            customer_name_override="PETCO DC 810",
        )

    assert result.ok is True
    mock_refresh.assert_awaited_once_with(
        tenant_id="00000000-0000-4000-8000-0000000000e1",
        tenant_slug="t3ra",
        turvo_shipment_id="1000324213",
        load_id="30381",
        customer_name_override="PETCO DC 810",
    )


@pytest.mark.asyncio
async def test_apply_tender_skips_when_already_tendered() -> None:
    svc = TurvoStopUpdateService()
    payload = _tender_app_payload(status_key="2101")
    mock_put = AsyncMock()

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.fetch_app_shipment_details",
            new=AsyncMock(return_value=payload),
        ),
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_shipment_tender_status",
            new=mock_put,
        ),
    ):
        result = await svc.apply_tender(tenant_slug="t3ra", shipment_id="1000324213")

    assert result.ok is True
    assert result.skipped is True
    assert result.updated is False
    mock_put.assert_not_awaited()


@pytest.mark.asyncio
async def test_apply_tender_missing_fragment_id() -> None:
    svc = TurvoStopUpdateService()
    payload = {"details": {"status": {"code": {"key": "2118"}}, "global_route": {"fragments": []}}}

    with patch(
        "app.services.appointment_scheduling.turvo_stop_update_service.fetch_app_shipment_details",
        new=AsyncMock(return_value=payload),
    ):
        result = await svc.apply_tender(tenant_slug="t3ra", shipment_id="1000324213")

    assert result.ok is False
    assert result.error == "missing_turvo_fragment_id"


@pytest.mark.asyncio
async def test_apply_tender_put_failure() -> None:
    svc = TurvoStopUpdateService()
    from app.integrations.turvo.public_api_client import TurvoApiError

    with (
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.fetch_app_shipment_details",
            new=AsyncMock(return_value=_tender_app_payload()),
        ),
        patch(
            "app.services.appointment_scheduling.turvo_stop_update_service.update_shipment_tender_status",
            new=AsyncMock(side_effect=TurvoApiError("fail", status_code=500)),
        ),
    ):
        result = await svc.apply_tender(tenant_slug="t3ra", shipment_id="1000324213")

    assert result.ok is False
    assert "fail" in (result.error or "")


def _placeholder_shipment_payload(
    *, route_stop: str = "Delivery WH", delivery_date: str = "2026-07-18"
) -> dict:
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
    svc = TurvoStopUpdateService()
    payload = _placeholder_shipment_payload()
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
    svc = TurvoStopUpdateService()
    result = await svc.apply_delivery_placeholder(
        tenant_slug="",
        shipment_id="",
    )
    assert result.ok is False
    assert result.error == "missing_turvo_update_fields"

