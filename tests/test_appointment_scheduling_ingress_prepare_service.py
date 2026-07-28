"""Tests for IngressPrepareService (worker Turvo/sheet/lifecycle path)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.appointment_scheduling.models import CustomerContactRow
from app.services.appointment_scheduling.ingress_prepare_service import (
    IngressPrepareService,
)

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_SHIPMENT_ID = "12345"
_LOAD_ID = "47361"
_SHIPMENTS_ROW_ID = "22222222-2222-2222-2222-222222222222"
_LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"


def _shipment_payload(*, reference: str = "DIAMOND-RPN-999") -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Acme Corp", "id": "CUST-1"},
                    "externalIds": [{"idValue": reference}],
                    "items": [{"deliveryLocation": [{"name": "PETCO DC 810"}]}],
                }
            ],
            "customId": _LOAD_ID,
            "globalRoute": [
                {"deleted": False, "name": "Pickup", "stopType": {"value": "Pickup"}},
                {
                    "deleted": False,
                    "name": "PETCO DC 810",
                    "stopType": {"value": "Delivery"},
                },
            ],
        }
    }


def _activity_json(*, pickup_changed: bool = True) -> dict:
    prev_date = "2026-03-20"
    final_date = "2026-03-21" if pickup_changed else prev_date
    return {
        "data": [
            {
                "record_metadata": {"created_by": {"name": "Ops User"}},
                "context_snapshot": {
                    "global_route": {"ship_locations": [{"type": {"key": "1500"}}, {}]},
                    "delta": {
                        "prev_diff_context": {
                            "global_route": {
                                "ship_locations": [
                                    {
                                        "type": {"key": "1500"},
                                        "appointment": {"date": prev_date},
                                    }
                                ]
                            }
                        },
                        "final_diff_context": {
                            "global_route": {
                                "ship_locations": [
                                    {
                                        "type": {"key": "1500"},
                                        "appointment": {"date": final_date},
                                    }
                                ]
                            }
                        },
                    },
                },
            }
        ]
    }


def _slim_payload() -> dict:
    return {
        "tenant_id": _TENANT_UUID,
        "tenant_slug": _TENANT_SLUG,
        "shipment_id": _SHIPMENT_ID,
        "load_id": _LOAD_ID,
    }


def _payload_with_shipment() -> dict:
    return {
        **_slim_payload(),
        "reference_number": "DIAMOND-RPN-999",
        "shipment": _shipment_payload(),
    }


def _service(
    *,
    upsert_success: bool = True,
    lifecycle_id: str | None = _LIFECYCLE_ID,
) -> IngressPrepareService:
    shipments = MagicMock()
    shipments.upsert_from_turvo.return_value = {
        "success": upsert_success,
        "shipments_row_id": _SHIPMENTS_ROW_ID if upsert_success else None,
    }
    lifecycle = MagicMock()
    if lifecycle_id:
        lifecycle.create_appointment_scheduling_lifecycle.return_value = lifecycle_id
    else:
        lifecycle.create_appointment_scheduling_lifecycle.side_effect = ValueError("bad")
    location = MagicMock()
    return IngressPrepareService(
        shipments_service=shipments,
        lifecycle_service=lifecycle,
        location_link_service=location,
    )


def _patch_activity(*, pickup_changed: bool = True):
    return patch(
        "app.services.appointment_scheduling.ingress_prepare_service.fetch_shipment_activity_list",
        new=AsyncMock(return_value=_activity_json(pickup_changed=pickup_changed)),
    )


@pytest.mark.asyncio
async def test_prepare_skips_missing_recipient_without_lifecycle() -> None:
    from app.domain.error_catalog import BusinessError

    svc = _service()
    with (
        _patch_activity(),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
            return_value=(BusinessError.MISSING_RECIPIENT_EMAIL, None),
        ),
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_payload_with_shipment(),
        )

    assert result.ok is False
    assert result.skip_reason == BusinessError.MISSING_RECIPIENT_EMAIL.value
    svc._shipments.upsert_from_turvo.assert_not_called()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_creates_lifecycle_when_recipient_resolves() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    with (
        _patch_activity(),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
            return_value=(None, contact),
        ),
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_payload_with_shipment(),
        )

    assert result.ok is True
    assert result.workflow_lifecycle_id == _LIFECYCLE_ID
    assert result.shipments_row_id == _SHIPMENTS_ROW_ID
    assert result.load_id == _LOAD_ID
    assert result.reference_number == "DIAMOND-RPN-999"
    assert result.customer_contact == contact
    assert result.shipment is None
    svc._shipments.upsert_from_turvo.assert_called_once()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_called_once()
    svc._location_link.try_link_from_turvo_shipment_payload.assert_called_once()


@pytest.mark.asyncio
async def test_prepare_fetches_shipment_when_not_on_payload() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    with (
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.get_shipment",
            new=AsyncMock(return_value=_shipment_payload()),
        ) as get_shipment_mock,
        _patch_activity(),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
            return_value=(None, contact),
        ),
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_slim_payload(),
        )

    assert result.ok is True
    assert result.workflow_lifecycle_id == _LIFECYCLE_ID
    get_shipment_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_prepare_skips_non_diamond_reference() -> None:
    svc = _service()
    with (
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.get_shipment",
            new=AsyncMock(return_value=_shipment_payload(reference="ACME-1")),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.fetch_shipment_activity_list",
            new=AsyncMock(),
        ) as activity_mock,
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_slim_payload(),
        )

    assert result.ok is False
    assert result.skip_reason == "non_diamond_customer"
    activity_mock.assert_not_called()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_skips_multi_stop_from_shipment() -> None:
    from tests.test_shipment_location_link import THREE_STOP_ROUTE

    svc = _service()
    multi = _shipment_payload()
    multi["details"]["globalRoute"] = THREE_STOP_ROUTE
    activity_mock = AsyncMock()
    with (
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.get_shipment",
            new=AsyncMock(return_value=multi),
        ),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.fetch_shipment_activity_list",
            new=activity_mock,
        ),
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_slim_payload(),
        )

    assert result.skip_reason == "multi_stop"
    activity_mock.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_skips_when_no_pickup_change() -> None:
    svc = _service()
    with (
        _patch_activity(pickup_changed=False),
        patch(
            "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
        ) as contact_mock,
    ):
        result = await svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_payload_with_shipment(),
        )

    assert result.skip_reason == "no_pickup_change"
    contact_mock.assert_not_called()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_reuses_existing_lifecycle_from_payload() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    payload = _payload_with_shipment()
    payload["workflow_lifecycle_id"] = _LIFECYCLE_ID
    payload["shipments_row_id"] = _SHIPMENTS_ROW_ID
    payload["customer_contact"] = contact.model_dump(mode="json")
    payload["customer_name"] = "PETCO DC 810"

    result = await svc.prepare_pickup_changed(
        tenant_slug=_TENANT_SLUG,
        tenant_id=_TENANT_UUID,
        tenant_settings={},
        payload=payload,
    )

    assert result.ok is True
    assert result.workflow_lifecycle_id == _LIFECYCLE_ID
    assert result.shipments_row_id == _SHIPMENTS_ROW_ID
    assert result.customer_contact == contact
    svc._shipments.upsert_from_turvo.assert_not_called()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_reuses_existing_lifecycle_without_shipment_on_payload() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    payload = {
        "tenant_id": _TENANT_UUID,
        "tenant_slug": _TENANT_SLUG,
        "shipment_id": _SHIPMENT_ID,
        "load_id": _LOAD_ID,
        "reference_number": "DIAMOND-RPN-999",
        "workflow_lifecycle_id": _LIFECYCLE_ID,
        "shipments_row_id": _SHIPMENTS_ROW_ID,
        "customer_contact": contact.model_dump(mode="json"),
        "customer_name": "PETCO DC 810",
    }

    result = await svc.prepare_pickup_changed(
        tenant_slug=_TENANT_SLUG,
        tenant_id=_TENANT_UUID,
        tenant_settings={},
        payload=payload,
    )

    assert result.ok is True
    assert result.shipment is None
    svc._shipments.upsert_from_turvo.assert_not_called()
