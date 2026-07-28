"""Appointment scheduling state keys and shared constants."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType

# Lifecycle metadata / checkpoint keys
EMAIL_DRAFT = "email_draft"
EMAIL_SENT = "email_sent"
APPOINTMENT_PAYLOAD = "appointment_payload"
LLM_APPOINTMENT_DECISION = "llm_appointment_decision"
WEEKEND_SHIFTED = "weekend_shifted"
APPOINTMENT_FAILURE_REASON = "appointment_failure_reason"

# Costco
COSTCO_PROPOSED_DELIVERY_WALL_TIME = "06:00"

# Turvo / ingress
APPOINTMENT_SCHEDULING_WORKFLOW = "appointment_scheduling"

SHIPMENT_UPDATE_EVENT_NAME = "SHIPMENT_UPDATE"

PICKUP_STOP_TYPE_KEY = "1500"

TURVO_SYSTEM_BOT_NAMES = frozenset(
    {
        "Turvo System Bot",
        "bot.tlsupport@turvo.com",
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
