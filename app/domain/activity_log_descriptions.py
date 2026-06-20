"""Human-readable ``activity_logs.description`` strings."""

from __future__ import annotations

from app.domain.activity_log_constants import (
    CARRIER_ACK_LLM_ACTION_TEMPLATE,
    DRIVER_DETAILS_LLM_ACTION_TEMPLATE,
    ESCALATION_SENT_ACTION,
    REMINDER_SENT_ACTION_TEMPLATE,
    STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    TENDER_CREATED_ACTION_TEMPLATE,
    TENDER_SENT_TO_VENDOR_ACTION,
    RATECON_RECEIVED_ACTION,
    RATECON_SUPERSEDED_ACTION,
    RATECON_DOCUMENT_UPLOADED_ACTION,
    RATECON_DOCUMENT_UPLOAD_FAILED_ACTION,
    RATECON_DOCUMENT_PROCESSED_ACTION,
    RATECON_DOCUMENT_PROCESSING_FAILED_ACTION,
    RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE,
    POD_STARTED_ACTION,
    DRIVER_ASSIGNMENT_STARTED_ACTION,
    DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE,
    DRIVER_ASSIGNMENT_CANCELLED_TENDERED_ACTION,
    DRIVER_REMINDERS_SCHEDULED_ACTION,
    DRIVER_REMINDER_SENT_TEMPLATE,
    DETAILS_RECEIVED_FROM_EMAIL_TEMPLATE,
    DRIVER_DETAILS_PARTIAL_FOLLOW_UP_TEMPLATE,
    DRIVER_FOUND_IN_TMS_TEMPLATE,
    DRIVER_NOT_FOUND_IN_TMS_TEMPLATE,
    DRIVER_AMBIGUOUS_IN_TMS_TEMPLATE,
    DRIVER_CREATED_IN_TMS_TEMPLATE,
    DRIVER_ASSIGNED_IN_TMS_ACTION,
    DRIVER_ALREADY_ASSIGNED_IN_TMS_ACTION,
    DRIVER_ASSIGN_TO_TMS_FAILED_TEMPLATE,
    DRIVER_CONFIRMATION_TRACKING_SENT_ACTION,
    DRIVER_CONFIRMATION_DEFAULT_SENT_ACTION,
    POD_ESCALATION_SENT_ACTION,
    POD_DOCUMENT_UPLOADED_ACTION,
    POD_DOCUMENT_UPLOAD_FAILED_ACTION,
    POD_DOCUMENT_PROCESSED_ACTION,
    POD_DOCUMENT_PROCESSING_FAILED_ACTION,
    POD_EXTRACTION_PROCESSED_TEMPLATE,
    POD_VS_RATECON_VALIDATED_TEMPLATE,
    POD_VS_RATECON_VALIDATION_SKIPPED_TEMPLATE,
    POD_VS_RATECON_VALIDATION_FAILED_ACTION,
    POD_UPLOADED_TO_TMS_ACTION,
    POD_UPLOAD_TO_TMS_FAILED_ACTION,
    POD_ALREADY_ON_TMS_ACTION,
    POD_REVIEW_ACKNOWLEDGED_ACTION,
)
from app.domain.error_catalog import error_description
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


def format_driver_details_llm_action(
    *,
    decision: str,
    reason: str,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    reason_s = (reason or "").strip() or "no reason"
    return DRIVER_DETAILS_LLM_ACTION_TEMPLATE.format(
        decision=decision,
        confidence_suffix=conf,
        reason=reason_s,
    )


def format_reminder_sent_action(*, step: int) -> str:
    return REMINDER_SENT_ACTION_TEMPLATE.format(step=step)


def format_escalation_sent_action() -> str:
    return ESCALATION_SENT_ACTION


def format_workflow_error_alert_sent_action(*, error_code: str) -> str:
    """Human-readable action text for one successful error alert delivery."""
    catalog_text = error_description(error_code)
    if catalog_text:
        return catalog_text
    return (error_code or "unknown").replace("_", " ").strip().title()


def format_ratecon_received_action() -> str:
    return RATECON_RECEIVED_ACTION


def format_ratecon_superseded_action() -> str:
    return RATECON_SUPERSEDED_ACTION


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


def format_driver_assignment_started_action() -> str:
    return DRIVER_ASSIGNMENT_STARTED_ACTION


def format_driver_assignment_not_started_action(*, reason: str) -> str:
    return DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE.format(reason=reason)


def format_driver_assignment_cancelled_tendered_action() -> str:
    return DRIVER_ASSIGNMENT_CANCELLED_TENDERED_ACTION


def format_driver_reminders_scheduled_action() -> str:
    return DRIVER_REMINDERS_SCHEDULED_ACTION


def format_driver_reminder_sent_action(*, step: int | None = None) -> str:
    label = str(step) if step is not None else "?"
    return DRIVER_REMINDER_SENT_TEMPLATE.format(step=label)


def format_details_received_from_email_action(
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
) -> str:
    contact_parts: list[str] = []
    if phone:
        contact_parts.append(f"phone={phone}")
    if email:
        contact_parts.append(f"email={email}")
    contact_suffix = f", {', '.join(contact_parts)}" if contact_parts else ""
    name_label = (name or "").strip() or "unknown"
    return DETAILS_RECEIVED_FROM_EMAIL_TEMPLATE.format(
        name=name_label,
        contact_suffix=contact_suffix,
    )


def format_driver_details_partial_follow_up_action(*, step: int | None = None) -> str:
    label = str(step) if step is not None else "?"
    return DRIVER_DETAILS_PARTIAL_FOLLOW_UP_TEMPLATE.format(step=label)


def format_driver_found_in_tms_action(
    *,
    match_by: str,
    match_value: str,
    contact_id: int | str,
) -> str:
    return DRIVER_FOUND_IN_TMS_TEMPLATE.format(
        match_by=match_by,
        match_value=match_value,
        contact_id=contact_id,
    )


def format_driver_not_found_in_tms_action(*, match_by: str, match_value: str) -> str:
    return DRIVER_NOT_FOUND_IN_TMS_TEMPLATE.format(
        match_by=match_by,
        match_value=match_value,
    )


def format_driver_ambiguous_in_tms_action(
    *, match_by: str, match_value: str, count: int
) -> str:
    return DRIVER_AMBIGUOUS_IN_TMS_TEMPLATE.format(
        match_by=match_by,
        match_value=match_value,
        count=count,
    )


def format_driver_created_in_tms_action(*, name: str, contact_id: int | str) -> str:
    return DRIVER_CREATED_IN_TMS_TEMPLATE.format(name=name, contact_id=contact_id)


def format_driver_assigned_in_tms_action() -> str:
    return DRIVER_ASSIGNED_IN_TMS_ACTION


def format_driver_already_assigned_in_tms_action() -> str:
    return DRIVER_ALREADY_ASSIGNED_IN_TMS_ACTION


def format_driver_assign_to_tms_failed_action(*, reason: str) -> str:
    return DRIVER_ASSIGN_TO_TMS_FAILED_TEMPLATE.format(reason=reason)


def format_driver_confirmation_tracking_sent_action() -> str:
    return DRIVER_CONFIRMATION_TRACKING_SENT_ACTION


def format_driver_confirmation_default_sent_action() -> str:
    return DRIVER_CONFIRMATION_DEFAULT_SENT_ACTION


def format_pod_escalation_sent_action() -> str:
    return POD_ESCALATION_SENT_ACTION


def format_pod_document_uploaded_action() -> str:
    return POD_DOCUMENT_UPLOADED_ACTION


def format_pod_document_upload_failed_action() -> str:
    return POD_DOCUMENT_UPLOAD_FAILED_ACTION


def format_pod_document_processed_action() -> str:
    return POD_DOCUMENT_PROCESSED_ACTION


def format_pod_document_processing_failed_action() -> str:
    return POD_DOCUMENT_PROCESSING_FAILED_ACTION


def format_pod_extraction_processed_action(
    *,
    confidence: float | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    return POD_EXTRACTION_PROCESSED_TEMPLATE.format(confidence_suffix=conf)


def format_pod_vs_ratecon_validated_action(
    *,
    confidence: float | None = None,
    status: str | None = None,
) -> str:
    conf = f" confidence={confidence:.2f}" if confidence is not None else ""
    status_label = (status or "UNKNOWN").strip().upper() or "UNKNOWN"
    return POD_VS_RATECON_VALIDATED_TEMPLATE.format(
        confidence_suffix=conf,
        status=status_label,
    )


def format_pod_vs_ratecon_validation_skipped_action(*, reason: str) -> str:
    reason_label = (reason or "unknown").strip() or "unknown"
    return POD_VS_RATECON_VALIDATION_SKIPPED_TEMPLATE.format(reason=reason_label)


def format_pod_vs_ratecon_validation_failed_action() -> str:
    return POD_VS_RATECON_VALIDATION_FAILED_ACTION


def format_pod_uploaded_to_tms_action() -> str:
    return POD_UPLOADED_TO_TMS_ACTION


def format_pod_upload_to_tms_failed_action() -> str:
    return POD_UPLOAD_TO_TMS_FAILED_ACTION


def format_pod_already_on_tms_action() -> str:
    return POD_ALREADY_ON_TMS_ACTION


def format_pod_review_acknowledged_action() -> str:
    return POD_REVIEW_ACKNOWLEDGED_ACTION
