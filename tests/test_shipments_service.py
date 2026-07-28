"""Unit tests for ShipmentsService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from datetime import datetime, timezone

from app.domain.shipment_display import ShipmentDisplayFields
from app.repositories.shipments_repository import ShipmentUpsertResult
from app.services.shipments_service import ShipmentsService
from tests.test_turvo_shipment_display_fields import SHIPMENT_1000324895_FIXTURE

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_upsert_from_turvo_rejects_missing_load_id():
    svc = ShipmentsService(shipments_repository=MagicMock())
    out = svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1000304706",
        load_id="  ",
    )
    assert out["success"] is False
    assert out["message"] == "missing_load_id"
    svc._shipments.upsert_by_tenant_and_shipment_number_tx.assert_not_called()


def test_upsert_from_turvo_metadata_includes_load_id():
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        created=True,
    )
    svc = ShipmentsService(shipments_repository=repo)

    out = svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1000304706",
        load_id="L42",
        metadata={"extra": "x"},
    )

    assert out["success"] is True
    assert out["created"] is True
    assert out["shipments_row_id"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    repo.upsert_by_tenant_and_shipment_number_tx.assert_called_once()
    call_kw = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs
    assert call_kw["tenant_id"] == _TENANT_UUID
    assert call_kw["shipment_number"] == "1000304706"
    assert call_kw["metadata"]["load_id"] == "L42"
    assert call_kw["metadata"]["extra"] == "x"


def test_upsert_from_turvo_caller_cannot_override_load_id_in_metadata():
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        created=False,
    )
    svc = ShipmentsService(shipments_repository=repo)

    svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="99",
        load_id="real-load",
        metadata={"load_id": "wrong"},
    )

    meta = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs["metadata"]
    assert meta["load_id"] == "real-load"


def test_upsert_from_turvo_soft_fails_on_repo_error():
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.side_effect = RuntimeError("db down")
    svc = ShipmentsService(shipments_repository=repo)

    out = svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1",
        load_id="L1",
    )

    assert out["success"] is False
    assert out["message"] == "shipments_upsert_failed"


def test_get_by_shipment_number_delegates_from_deprecated_turvo_alias():
    repo = MagicMock()
    repo.get_by_tenant_and_shipment_number_tx.return_value = {
        "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        "shipment_number": "1000324895",
    }
    svc = ShipmentsService(shipments_repository=repo)

    out = svc.get_by_turvo_shipment_number(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1000324895",
    )

    assert out is not None
    repo.get_by_tenant_and_shipment_number_tx.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_number="1000324895",
    )


def test_get_by_id_delegates_to_repo():
    repo = MagicMock()
    repo.get_by_tenant_and_id_tx.return_value = {
        "id": _SHIPMENTS_ROW_UUID,
        "shipment_number": "1000324895",
    }
    svc = ShipmentsService(shipments_repository=repo)

    out = svc.get_by_id(
        tenant_id=_TENANT_UUID,
        shipment_id=_SHIPMENTS_ROW_UUID,
    )

    assert out is not None
    repo.get_by_tenant_and_id_tx.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_id=_SHIPMENTS_ROW_UUID,
    )


def test_upsert_from_turvo_maps_turvo_payload_to_display_columns():
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id=_SHIPMENTS_ROW_UUID,
        created=True,
    )
    svc = ShipmentsService(shipments_repository=repo)

    out = svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1000324895",
        load_id="30389",
        turvo_payload=SHIPMENT_1000324895_FIXTURE,
    )

    assert out["success"] is True
    call_kw = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs
    assert call_kw["customer_name"] == "DIAMOND PET FOODS"
    assert call_kw["carrier_name"] == "Turvo Test Carrier"
    assert call_kw["delivery_date"] == datetime(2026, 4, 1, 7, 1, tzinfo=timezone.utc)
    assert call_kw["delivery_timezone"] == "America/New_York"
    assert call_kw["pickup_date"] == datetime(2026, 3, 30, 14, 0, tzinfo=timezone.utc)
    assert call_kw["pickup_timezone"] == "America/Los_Angeles"


def test_upsert_from_turvo_accepts_explicit_display_fields():
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id=_SHIPMENTS_ROW_UUID,
        created=False,
    )
    svc = ShipmentsService(shipments_repository=repo)

    svc.upsert_from_turvo(
        tenant_id=_TENANT_UUID,
        turvo_shipment_id="1",
        load_id="L1",
        display_fields=ShipmentDisplayFields(
            carrier_name="Carrier A",
            customer_name="Customer B",
            delivery_date=datetime(2026, 1, 2, 8, 30, tzinfo=timezone.utc),
            delivery_timezone="America/New_York",
            pickup_date=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            pickup_timezone="America/Chicago",
        ),
    )

    call_kw = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs
    assert call_kw["carrier_name"] == "Carrier A"
    assert call_kw["customer_name"] == "Customer B"
    assert call_kw["delivery_date"] == datetime(2026, 1, 2, 8, 30, tzinfo=timezone.utc)
    assert call_kw["delivery_timezone"] == "America/New_York"
    assert call_kw["pickup_date"] == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert call_kw["pickup_timezone"] == "America/Chicago"


def test_get_by_id_returns_none_for_invalid_uuid():
    svc = ShipmentsService(shipments_repository=MagicMock())

    assert svc.get_by_id(tenant_id=_TENANT_UUID, shipment_id="1000324895") is None
    svc._shipments.get_by_tenant_and_id_tx.assert_not_called()


def test_clear_driver_details_delegates_to_repo():
    repo = MagicMock()
    repo.clear_driver_details_tx.return_value = True
    svc = ShipmentsService(shipments_repository=repo)

    ok = svc.clear_driver_details(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENTS_ROW_UUID,
    )

    assert ok is True
    repo.clear_driver_details_tx.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENTS_ROW_UUID,
    )


def test_clear_driver_details_returns_false_for_invalid_ids():
    svc = ShipmentsService(shipments_repository=MagicMock())

    assert svc.clear_driver_details(tenant_id="", shipment_row_id=_SHIPMENTS_ROW_UUID) is False
    svc._shipments.clear_driver_details_tx.assert_not_called()


def test_update_proposed_appointments_delegates_parsed_dates_to_repo():
    repo = MagicMock()
    repo.get_by_tenant_and_id_tx.return_value = None
    repo.update_proposed_appointments_tx.return_value = True
    svc = ShipmentsService(shipments_repository=repo)

    ok = svc.update_proposed_appointments(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENTS_ROW_UUID,
        proposed_pickup_at="2026-07-30",
        proposed_delivery_at="08/04/2026",
    )

    assert ok is True
    repo.update_proposed_appointments_tx.assert_called_once()
    kwargs = repo.update_proposed_appointments_tx.call_args.kwargs
    assert kwargs["tenant_id"] == _TENANT_UUID
    assert kwargs["shipment_row_id"] == _SHIPMENTS_ROW_UUID
    assert kwargs["proposed_pickup"] == datetime(2026, 7, 30, tzinfo=timezone.utc)
    assert kwargs["proposed_delivery"] == datetime(2026, 8, 4, tzinfo=timezone.utc)


def test_update_proposed_appointments_uses_stop_timezone_and_wall_time():
    repo = MagicMock()
    repo.update_proposed_appointments_tx.return_value = True
    svc = ShipmentsService(shipments_repository=repo)

    ok = svc.update_proposed_appointments(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENTS_ROW_UUID,
        proposed_delivery_at="07/04/2026",
        proposed_delivery_time="06:00",
        delivery_timezone="America/Chicago",
    )

    assert ok is True
    kwargs = repo.update_proposed_appointments_tx.call_args.kwargs
    stored = kwargs["proposed_delivery"]
    assert stored is not None
    assert stored.hour == 11
    assert stored.minute == 0
    repo.get_by_tenant_and_id_tx.assert_not_called()


def test_update_proposed_appointments_noop_when_unparseable():
    repo = MagicMock()
    svc = ShipmentsService(shipments_repository=repo)

    ok = svc.update_proposed_appointments(
        tenant_id=_TENANT_UUID,
        shipment_row_id=_SHIPMENTS_ROW_UUID,
        proposed_pickup_at="bad",
        proposed_delivery_at="",
    )

    assert ok is False
    repo.update_proposed_appointments_tx.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_display_from_turvo_fetches_and_upserts() -> None:
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id=_SHIPMENTS_ROW_UUID,
        created=False,
    )
    svc = ShipmentsService(shipments_repository=repo)

    with patch(
        "app.services.shipments_service.get_turvo_shipment_async",
        new=AsyncMock(return_value=SHIPMENT_1000324895_FIXTURE),
    ):
        out = await svc.refresh_display_from_turvo(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            turvo_shipment_id="1000324895",
            load_id="30389",
        )

    assert out["success"] is True
    repo.upsert_by_tenant_and_shipment_number_tx.assert_called_once()
    call_kw = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs
    assert call_kw["delivery_date"] == datetime(2026, 4, 1, 7, 1, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_refresh_display_from_turvo_applies_customer_name_override() -> None:
    repo = MagicMock()
    repo.upsert_by_tenant_and_shipment_number_tx.return_value = ShipmentUpsertResult(
        shipment_id=_SHIPMENTS_ROW_UUID,
        created=False,
    )
    svc = ShipmentsService(shipments_repository=repo)

    with patch(
        "app.services.shipments_service.get_turvo_shipment_async",
        new=AsyncMock(return_value=SHIPMENT_1000324895_FIXTURE),
    ):
        out = await svc.refresh_display_from_turvo(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            turvo_shipment_id="1000324895",
            load_id="30389",
            customer_name_override="PETCO DC 810",
        )

    assert out["success"] is True
    call_kw = repo.upsert_by_tenant_and_shipment_number_tx.call_args.kwargs
    assert call_kw["customer_name"] == "PETCO DC 810"


@pytest.mark.asyncio
async def test_refresh_display_from_turvo_soft_fails_on_get_error() -> None:
    svc = ShipmentsService(shipments_repository=MagicMock())

    with patch(
        "app.services.shipments_service.get_turvo_shipment_async",
        new=AsyncMock(side_effect=RuntimeError("turvo down")),
    ):
        out = await svc.refresh_display_from_turvo(
            tenant_id=_TENANT_UUID,
            tenant_slug="t3ra",
            turvo_shipment_id="1000324895",
            load_id="30389",
        )

    assert out["success"] is False
    assert out["message"] == "turvo_get_shipment_failed"
    svc._shipments.upsert_by_tenant_and_shipment_number_tx.assert_not_called()
