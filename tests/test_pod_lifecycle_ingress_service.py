"""Tests for PodLifecycleIngressService route_completed dedupe."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.pod_lifecycle_ingress_service import PodLifecycleIngressService

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_LIFECYCLE_UUID = "11111111-2222-3333-4444-555555555555"
_TURVO_SHIPMENT = "1000324895"


def test_check_route_completed_duplicate_not_route_completed_event() -> None:
    svc = PodLifecycleIngressService()
    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "email_received", "shipment_id": _TURVO_SHIPMENT},
    )
    assert result.is_duplicate is False


def test_check_route_completed_duplicate_no_shipments_row() -> None:
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = None
    svc = PodLifecycleIngressService(shipments_service=shipments)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
    )

    assert result.is_duplicate is False
    assert result.lifecycle_id is None


def test_check_route_completed_duplicate_first_time_no_lifecycle() -> None:
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    svc = PodLifecycleIngressService(lifecycle_service=lifecycle)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={
            "event_type": "route_completed",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
        },
    )

    assert result.is_duplicate is False
    assert result.shipments_row_id == _SHIPMENTS_ROW_UUID
    lifecycle.check_lifecycle_exists.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        workflow_name="pod_lifecycle",
        shipment_id=_SHIPMENTS_ROW_UUID,
    )


def test_check_route_completed_duplicate_when_prior_run_exists() -> None:
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {
        "exists": True,
        "lifecycle_id": _LIFECYCLE_UUID,
    }
    runs = MagicMock()
    runs.is_workflow_initial_path_blocked.return_value = True
    svc = PodLifecycleIngressService(lifecycle_service=lifecycle, runs_service=runs)

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={
            "event_type": "route_completed",
            "shipments_row_id": _SHIPMENTS_ROW_UUID,
        },
    )

    assert result.is_duplicate is True
    assert result.lifecycle_id == _LIFECYCLE_UUID
    runs.is_workflow_initial_path_blocked.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        event_type="route_completed",
        workflow_lifecycle_id=_LIFECYCLE_UUID,
        shipment_id=_SHIPMENTS_ROW_UUID,
        exclude_run_id=None,
    )


def test_check_route_completed_duplicate_resolves_shipments_row_from_turvo_number() -> None:
    shipments = MagicMock()
    shipments.get_by_shipment_number.return_value = {"id": _SHIPMENTS_ROW_UUID}
    lifecycle = MagicMock()
    lifecycle.check_lifecycle_exists.return_value = {"exists": False}
    svc = PodLifecycleIngressService(
        lifecycle_service=lifecycle,
        shipments_service=shipments,
    )

    result = svc.check_route_completed_duplicate(
        tenant_id=_TENANT_UUID,
        payload={"event_type": "route_completed", "shipment_id": _TURVO_SHIPMENT},
    )

    assert result.is_duplicate is False
    shipments.get_by_shipment_number.assert_called_once_with(
        tenant_id=_TENANT_UUID,
        shipment_number=_TURVO_SHIPMENT,
    )
