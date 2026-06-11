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
    REMINDER_3_SENT = "reminder_3_sent"
    POD_STARTED = "pod_started"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DO_NOTHING = "do_nothing"
    ESCALATED = "escalated"
    RATECON_STARTED = "ratecon_started"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_PROCESSED = "document_processed"
    UPLOADED_TO_TMS = "uploaded_to_tms"
