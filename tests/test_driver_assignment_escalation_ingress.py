"""Tests for driver assignment escalation ingress eligibility."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from tests.test_turvo_driver_request_eligibility import _eligible_payload


def test_check_escalation_eligibility_requires_lifecycle_id() -> None:
    svc = DriverAssignmentIngressService()
    result = svc.check_escalation_eligibility(
        tenant_id="tenant-1",
        payload={
            "load_id": "30389",
            "shipment_id": "100",
            "shipments_row_id": "row-1",
        },
    )
    assert result.skip_reason == "missing_correlation_keys"


def test_check_escalation_eligibility_skips_when_already_escalated() -> None:
    svc = DriverAssignmentIngressService(lifecycle_service=MagicMock())
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "escalated",
    }
    result = svc.check_escalation_eligibility(
        tenant_id="tenant-1",
        payload={
            "load_id": "30389",
            "shipment_id": "100",
            "shipments_row_id": "row-1",
            "workflow_lifecycle_id": "wl-1",
        },
    )
    assert result.skip_reason == "already_escalated"


def test_check_escalation_eligibility_ok_without_thread_id() -> None:
    svc = DriverAssignmentIngressService(lifecycle_service=MagicMock())
    svc._lifecycle_service.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "reminder_4_sent",
    }
    result = svc.check_escalation_eligibility(
        tenant_id="tenant-1",
        payload={
            "load_id": "30389",
            "shipment_id": "100",
            "shipments_row_id": "row-1",
            "workflow_lifecycle_id": "wl-1",
            "shipment": _eligible_payload(),
        },
    )
    assert result.skip_reason is None
