"""Typed ``workflow_lifecycles`` / ``activity_logs`` lifecycle status values."""

from __future__ import annotations

from enum import StrEnum


class StatusType(StrEnum):
    """Top-level lifecycle progress (cross-workflow)."""

    NONE = "none"
    PENDING_REVIEW = "pending_review"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StatusSubType(StrEnum):
    """Lifecycle drill-down; extend per workflow as columns stay a single TEXT field."""

    NONE = "none"
    TENDER_CREATED = "tender_created"
    TENDER_SENT_TO_TENANT = "tender_sent_to_tenant"
    TENDER_SENT_TO_CARRIER = "tender_sent_to_carrier"
    REMINDER_1_SENT = "reminder_1_sent"
    REMINDER_2_SENT = "reminder_2_sent"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ESCALATED = "escalated"