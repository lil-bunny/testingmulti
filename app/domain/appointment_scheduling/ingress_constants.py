"""Constants for appointment scheduling Turvo ingress gates."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType

APPOINTMENT_SCHEDULING_WORKFLOW = "appointment_scheduling"

SHIPMENT_UPDATE_EVENT_NAME = "SHIPMENT_UPDATE"

TENDER_ACCEPTED_STATUS_VALUES = frozenset(
    {
        "tender-accepted",
        "tendered-accepted",
    }
)

PICKUP_STOP_TYPE_KEY = "1500"

TURVO_SYSTEM_BOT_NAMES = frozenset(
    {
        "Turvo System Bot",
        "bot.tlsupport@turvo.com",
    }
)

SCHEDULING_BLOCKING_SUB_STATUSES = frozenset(
    {
        "appointment_draft_created",
        "awaiting_customer_reply",
    }
)

SCHEDULING_REPLY_TERMINAL_STATUSES = frozenset(
    {
        StatusType.COMPLETED,
        StatusType.FAILED,
    }
)

SCHEDULING_REPLY_TERMINAL_SUB_STATUSES = frozenset(
    {
        StatusSubType.RESOLVED_MANUALLY,
    }
)

SCHEDULING_INGRESS_SKIP_REASONS = frozenset(
    {
        "tenant_not_resolved",
        "process_disabled",
        "event_not_shipment_update",
        "missing_shipment_id",
        "status_not_tender_accepted",
        "turvo_not_configured",
        "turvo_activity_fetch_failed",
        "multi_stop",
        "no_pickup_change",
        "turvo_shipment_fetch_failed",
        "missing_reference_number",
        "missing_load_id",
        "non_diamond_customer",
        "duplicate_lifecycle",
        "lifecycle_create_failed",
        "enqueue_failed",
        "appointment_mode_not_email",
    }
)
