"""Turvo workflow cancel trigger mapper tests."""

from __future__ import annotations

from app.domain.workflow_cancel_trigger import SHIPMENT_TENDERED_TRIGGER
from app.integrations.turvo.webhook_mapping import TurvoStatusWebhookEvent
from app.integrations.turvo.workflow_cancel import shipment_tendered_trigger_from_turvo


def test_shipment_tendered_trigger_from_turvo() -> None:
    event = TurvoStatusWebhookEvent(
        status_key="2101",
        shipment_id="1000324895",
        load_id="30389",
    )
    trigger = shipment_tendered_trigger_from_turvo(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        event=event,
    )
    assert trigger.trigger == SHIPMENT_TENDERED_TRIGGER
    assert trigger.shipment_number == "1000324895"
    assert trigger.load_id == "30389"
    assert trigger.metadata["vendor"] == "turvo"
    assert trigger.metadata["turvo_status_key"] == "2101"
