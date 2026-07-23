"""Tests for AppointmentSchedulingIngressPrepareService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.appointment_scheduling.models import CustomerContactRow
from app.services.appointment_scheduling.ingress_prepare_service import (
    AppointmentSchedulingIngressPrepareService,
)

_TENANT_SLUG = "t3ra"
_TENANT_UUID = "11111111-1111-1111-1111-111111111111"
_SHIPMENT_ID = "12345"
_LOAD_ID = "47361"
_SHIPMENTS_ROW_ID = "22222222-2222-2222-2222-222222222222"
_LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"


def _shipment_payload() -> dict:
    return {
        "details": {
            "customerOrder": [
                {
                    "deleted": False,
                    "customer": {"name": "Acme Corp", "id": "CUST-1"},
                    "externalIds": [{"idValue": "DIAMOND-RPN-999"}],
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


def _payload() -> dict:
    return {
        "tenant_id": _TENANT_UUID,
        "tenant_slug": _TENANT_SLUG,
        "shipment_id": _SHIPMENT_ID,
        "load_id": _LOAD_ID,
        "reference_number": "DIAMOND-RPN-999",
        "shipment": _shipment_payload(),
    }


def _service(
    *,
    upsert_success: bool = True,
    lifecycle_id: str | None = _LIFECYCLE_ID,
) -> AppointmentSchedulingIngressPrepareService:
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
    return AppointmentSchedulingIngressPrepareService(
        shipments_service=shipments,
        lifecycle_service=lifecycle,
        location_link_service=location,
    )


def test_prepare_skips_missing_recipient_without_lifecycle() -> None:
    svc = _service()
    with patch(
        "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
        return_value=("missing_recipient_email", None),
    ):
        result = svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_payload(),
        )

    assert result.ok is False
    assert result.skip_reason == "missing_recipient_email"
    svc._shipments.upsert_from_turvo.assert_not_called()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_not_called()


def test_prepare_creates_lifecycle_when_recipient_resolves() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    with patch(
        "app.services.appointment_scheduling.ingress_prepare_service.resolve_recipient_contact",
        return_value=(None, contact),
    ):
        result = svc.prepare_pickup_changed(
            tenant_slug=_TENANT_SLUG,
            tenant_id=_TENANT_UUID,
            tenant_settings={},
            payload=_payload(),
        )

    assert result.ok is True
    assert result.workflow_lifecycle_id == _LIFECYCLE_ID
    assert result.shipments_row_id == _SHIPMENTS_ROW_ID
    assert result.customer_contact == contact
    svc._shipments.upsert_from_turvo.assert_called_once()
    svc._lifecycle.create_appointment_scheduling_lifecycle.assert_called_once()
    svc._location_link.try_link_from_turvo_shipment_payload.assert_called_once()


def test_prepare_reuses_existing_lifecycle_from_payload() -> None:
    contact = CustomerContactRow(email="wh@example.com", customer="PETCO DC 810")
    svc = _service()
    payload = _payload()
    payload["workflow_lifecycle_id"] = _LIFECYCLE_ID
    payload["shipments_row_id"] = _SHIPMENTS_ROW_ID
    payload["customer_contact"] = contact.model_dump(mode="json")
    payload["customer_name"] = "PETCO DC 810"

    result = svc.prepare_pickup_changed(
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
