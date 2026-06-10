"""Human-readable ``activity_logs.description`` strings."""

from __future__ import annotations

from app.domain.activity_log_constants import (
    CARRIER_ACK_LLM_ACTION_TEMPLATE,
    ESCALATION_SENT_ACTION,
    REMINDER_SENT_ACTION_TEMPLATE,
    STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    TENDER_CREATED_ACTION_TEMPLATE,
    TENDER_SENT_TO_VENDOR_ACTION,
    RATECON_RECEIVED_ACTION,
    RATECON_DOCUMENT_UPLOADED_ACTION,
    RATECON_DOCUMENT_UPLOAD_FAILED_ACTION,
    RATECON_DOCUMENT_PROCESSED_ACTION,
    RATECON_DOCUMENT_PROCESSING_FAILED_ACTION,
    RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE,
    POD_STARTED_ACTION,
    POD_ESCALATION_SENT_ACTION,
    POD_UPLOADED_TO_TMS_ACTION,
    POD_UPLOAD_TO_TMS_FAILED_ACTION,
    POD_ALREADY_ON_TMS_ACTION,
)
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType


def _label_status(value: StatusType) -> str:
    if value == StatusType.NONE:
        return "None"
    return value.value.replace("_", " ").title()


def _label_sub_status(value: StatusSubType) -> str:
    if value == StatusSubType.NONE:
        return "None"
    return value.value.replace("_", " ").title()


def generate_activity_log_description(
    *,
    activity_type: ActivityType,
    from_status: StatusType,
    to_status: StatusType,
    from_sub_status: StatusSubType,
    to_sub_status: StatusSubType,
) -> str | None:
    """
    Build a transition description from templates.

    ``STATUS_CHANGE``: status line only (sub-status columns may still differ).
    ``SUB_STATUS_CHANGE``: sub-status line only.
    ``ACTION``: no template — callers supply narrative text.
    """
    if activity_type == ActivityType.STATUS_CHANGE:
        if from_status == to_status:
            return None
        return STATUS_CHANGE_DESCRIPTION_TEMPLATE.format(
            from_status=_label_status(from_status),
            to_status=_label_status(to_status),
        )
    if activity_type == ActivityType.SUB_STATUS_CHANGE:
        if from_sub_status == to_sub_status:
            return None
        return SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE.format(
            from_sub_status=_label_sub_status(from_sub_status),
            to_sub_status=_label_sub_status(to_sub_status),
        )
    return None


def format_tender_created_action(
    *,
    tender_id: str,
    order_number: str,
    customer_name: str,
) -> str:
    order = (order_number or "").strip() or tender_id
    customer = (customer_name or "").strip() or "Unknown"
    return TENDER_CREATED_ACTION_TEMPLATE.format(
        order_number=order,
        customer_name=customer,
    )


def format_tender_sent_to_vendor() -> str:
    return TENDER_SENT_TO_VENDOR_ACTION


def format_carrier_ack_llm_action(
    *,
    decision: str,
    reason: str,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    reason_s = (reason or "").strip() or "no reason"
    return CARRIER_ACK_LLM_ACTION_TEMPLATE.format(
        decision=decision,
        confidence_suffix=conf,
        reason=reason_s,
    )


def format_reminder_sent_action(*, step: int) -> str:
    return REMINDER_SENT_ACTION_TEMPLATE.format(step=step)


def format_escalation_sent_action() -> str:
    return ESCALATION_SENT_ACTION


def format_workflow_error_alert_sent_action(*, channel: str) -> str:
    """Human-readable action text for one successful error alert delivery."""
    label = (channel or "unknown").replace("_", " ").strip().title()
    return f"Workflow error alert sent ({label})"


def format_ratecon_received_action() -> str:
    return RATECON_RECEIVED_ACTION


def format_ratecon_document_uploaded_action() -> str:
    return RATECON_DOCUMENT_UPLOADED_ACTION


def format_ratecon_document_upload_failed_action() -> str:
    return RATECON_DOCUMENT_UPLOAD_FAILED_ACTION


def format_ratecon_document_processed_action() -> str:
    return RATECON_DOCUMENT_PROCESSED_ACTION


def format_ratecon_document_processing_failed_action() -> str:
    return RATECON_DOCUMENT_PROCESSING_FAILED_ACTION


def format_ratecon_document_processed_with_llm_action(
    *,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    return RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE.format(
        confidence_suffix=conf,
    )


def format_pod_started_action() -> str:
    return POD_STARTED_ACTION


def format_pod_escalation_sent_action() -> str:
    return POD_ESCALATION_SENT_ACTION


def format_pod_uploaded_to_tms_action() -> str:
    return POD_UPLOADED_TO_TMS_ACTION


def format_pod_upload_to_tms_failed_action() -> str:
    return POD_UPLOAD_TO_TMS_FAILED_ACTION


def format_pod_already_on_tms_action() -> str:
    return POD_ALREADY_ON_TMS_ACTION
