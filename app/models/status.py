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
    TENDER_SENT_TO_TENANT_FOR_CARRIER_1 = "tender_sent_to_tenant_for_carrier_1"
    TENDER_SENT_TO_TENANT_FOR_CARRIER_2 = "tender_sent_to_tenant_for_carrier_2"
    TENDER_SENT_TO_TENANT_FOR_CARRIER_3 = "tender_sent_to_tenant_for_carrier_3"
    TENDER_SENT_TO_CARRIER = "tender_sent_to_carrier"
    TENDER_SENT_TO_CARRIER_1 = "tender_sent_to_carrier_1"
    TENDER_SENT_TO_CARRIER_2 = "tender_sent_to_carrier_2"
    TENDER_SENT_TO_CARRIER_3 = "tender_sent_to_carrier_3"
    REMINDER_1_SENT = "reminder_1_sent"
    REMINDER_2_SENT = "reminder_2_sent"
    REMINDER_3_SENT = "reminder_3_sent"
    REMINDER_4_SENT = "reminder_4_sent"
    POD_STARTED = "pod_started"
    DRIVER_ASSIGNMENT_STARTED = "driver_assignment_started"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    DO_NOTHING = "do_nothing"
    ESCALATED = "escalated"
    RATECON_STARTED = "ratecon_started"
    DOCUMENT_UPLOADED = "document_uploaded"
    DOCUMENT_PROCESSED = "document_processed"
    UPLOADED_TO_TMS = "uploaded_to_tms"
    CANCELLED = "cancelled"
    RESOLVED_MANUALLY = "resolved_manually"
