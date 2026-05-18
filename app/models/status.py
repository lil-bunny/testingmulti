"""Typed ``workflow_lifecycles.status`` / ``sub_status`` values (DB stores plain text)."""

from __future__ import annotations

from enum import StrEnum


class StatusType(StrEnum):
    """Top-level lifecycle progress (cross-workflow)."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PENDING_REVIEW = "pending_review"


class StatusSubType(StrEnum):
    """Lifecycle drill-down; extend per workflow as columns stay a single TEXT field."""

    # Gelita load_tendering
    AWAITING_RESPONSE = "awaiting_response"
    AWAITING_RESPONSE_REMINDERS_QUEUED = "awaiting_response_reminders_queued"
    TENDER_SENT = "tender_sent"
    TENDER_EMAIL_FAILED = "tender_email_failed"
    REMINDER_1_SENT = "reminder_1_sent"
    REMINDER_2_SENT = "reminder_2_sent"
    ACCEPTED = "accepted"
    ESCALATED = "escalated"
