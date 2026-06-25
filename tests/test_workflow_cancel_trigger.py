"""WorkflowCancelTrigger validation tests."""

from __future__ import annotations

from app.domain.workflow_cancel_trigger import (
    SHIPMENT_TENDERED_TRIGGER,
    WorkflowCancelTrigger,
)


def test_shipment_correlation_error_when_both_missing() -> None:
    trigger = WorkflowCancelTrigger(
        trigger=SHIPMENT_TENDERED_TRIGGER,
        tenant_id="t1",
        tenant_slug="t3ra",
    )
    assert trigger.shipment_correlation_error() == "missing_shipment_correlation"


def test_shipment_correlation_ok_with_number() -> None:
    trigger = WorkflowCancelTrigger(
        trigger=SHIPMENT_TENDERED_TRIGGER,
        tenant_id="t1",
        tenant_slug="t3ra",
        shipment_number="1000324895",
    )
    assert trigger.shipment_correlation_error() is None
