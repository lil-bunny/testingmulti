"""Map Turvo webhook events to workflow cancel triggers."""

from __future__ import annotations

from app.domain.workflow_cancel_trigger import (
    SHIPMENT_TENDERED_TRIGGER,
    WorkflowCancelTrigger,
)
from app.integrations.turvo.webhook_mapping import (
    TENDERED_STATUS_CODE_KEY,
    TurvoStatusWebhookEvent,
)


def shipment_tendered_trigger_from_turvo(
    *,
    tenant_id: str,
    tenant_slug: str,
    event: TurvoStatusWebhookEvent,
) -> WorkflowCancelTrigger:
    return WorkflowCancelTrigger(
        trigger=SHIPMENT_TENDERED_TRIGGER,
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        shipment_number=event.shipment_id,
        load_id=event.load_id,
        metadata={
            "vendor": "turvo",
            "turvo_status_key": TENDERED_STATUS_CODE_KEY,
        },
    )
