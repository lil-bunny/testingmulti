"""Appointment scheduling keys, ingress gates, and shared constants."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType

# Lifecycle metadata / checkpoint keys
EMAIL_DRAFT = "email_draft"
DRAFT_SEND_QUEUED = "draft_send_queued"
APPOINTMENT_PAYLOAD = "appointment_payload"
LLM_APPOINTMENT_DECISION = "llm_appointment_decision"
APPOINTMENT_FAILURE_REASON = "appointment_failure_reason"
APPOINTMENT_INGRESS_SKIP_REASON = "appointment_ingress_skip_reason"
APPOINTMENT_INTAKE_SKIP_REASON = "appointment_intake_skip_reason"

# Costco
COSTCO_PROPOSED_DELIVERY_WALL_TIME = "06:00"

# Turvo / ingress
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
        StatusSubType.REJECTED,
        StatusSubType.APPOINTMENT_SCHEDULED,
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
