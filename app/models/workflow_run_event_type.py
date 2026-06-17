"""``workflow_runs.event_type`` — graph invocation trigger label."""

from __future__ import annotations

from enum import StrEnum


class WorkflowRunEventType(StrEnum):
    """
    Persisted on ``workflow_runs.event_type``.

    Load tendering (Unipile / ``email_webhook_attachment_ingestion`` → Gelita ingress):
    ``email_received``, ``tender_created``, ``carrier_email_received``, ``ack_received``,
    ``reminder_due``, ``escalation_due``.

    POD / Turvo: ``route_completed``, ``email_received``, ``manual_pod_upload``, ``reminder_due``.

    Driver assignment (ratecon tail): ``ratecon_completed``.
    """

    ROUTE_COMPLETED = "route_completed"
    RATECON_COMPLETED = "ratecon_completed"
    EMAIL_RECEIVED = "email_received"
    MANUAL_POD_UPLOAD = "manual_pod_upload"
    REMINDER_DUE = "reminder_due"
    TENDER_CREATED = "tender_created"
    CARRIER_EMAIL_RECEIVED = "carrier_email_received"
    ACK_RECEIVED = "ack_received"
    ESCALATION_DUE = "escalation_due"
