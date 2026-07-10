"""Human-readable ``activity_logs.description`` strings."""

from __future__ import annotations

from app.domain.activity_log_constants import (
    AUTO_REPLY_ACK_SKIPPED_ACTION,
    CARRIER_ACK_LLM_ACTION_TEMPLATE,
    ESCALATION_SENT_ACTION,
    POD_FOUND_IN_TMS_INFO,
    POD_DOCUMENT_PROCESSED_ACTION,
    POD_DOCUMENT_PROCESSING_FAILED_ACTION,
    POD_DOCUMENT_UPLOADED_ACTION,
    POD_DOCUMENT_UPLOAD_FAILED_ACTION,
    POD_UPLOADED_MANUALLY_INFO,
    POD_ESCALATION_SENT_ACTION,
    POD_EXTRACTION_PROCESSED_TEMPLATE,
    POD_UPLOADED_TO_TMS_ACTION,
    POD_UPLOAD_TO_TMS_FAILED_ACTION,
    POD_VS_RATECON_VALIDATED_TEMPLATE,
    POD_VS_RATECON_VALIDATION_FAILED_ACTION,
    POD_VS_RATECON_VALIDATION_SKIPPED_TEMPLATE,
    RATECON_DOCUMENT_PROCESSED_ACTION,
    RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE,
    RATECON_DOCUMENT_PROCESSING_FAILED_ACTION,
    RATECON_DOCUMENT_UPLOADED_ACTION,
    RATECON_DOCUMENT_UPLOAD_FAILED_ACTION,
    RATECON_RECEIVED_ACTION,
    RATECON_SUPERSEDED_ACTION,
    REMINDER_SENT_ACTION_TEMPLATE,
    STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE,
    TENDER_CREATED_ACTION_TEMPLATE,
    TENDER_SENT_TO_TENANT_ACTION,
    WORKFLOW_REVIEW_ACKNOWLEDGED_ACTION,
    WORKFLOW_REVIEW_RESOLVED_ACTION,
    TMS_CONNECTION_TIMED_OUT_EXCEPTION,
)
from app.domain.status_display_labels import label_status, label_sub_status
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType


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
    ``ACTION`` / ``EXCEPTION`` / ``INFO``: no template — callers supply narrative text.
    """
    if activity_type == ActivityType.STATUS_CHANGE:
        if from_status == to_status:
            return None
        return STATUS_CHANGE_DESCRIPTION_TEMPLATE.format(
            from_status=label_status(from_status),
            to_status=label_status(to_status),
        )
    if activity_type == ActivityType.SUB_STATUS_CHANGE:
        if from_sub_status == to_sub_status:
            return None
        return SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE.format(
            from_sub_status=label_sub_status(from_sub_status),
            to_sub_status=label_sub_status(to_sub_status),
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


def format_tender_sent_to_tenant() -> str:
    return TENDER_SENT_TO_TENANT_ACTION


def format_auto_reply_ack_skipped_action() -> str:
    """ACTION text when carrier ack LLM is skipped for an automatic reply."""
    return AUTO_REPLY_ACK_SKIPPED_ACTION


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


def format_pod_escalation_sent_action() -> str:
    return POD_ESCALATION_SENT_ACTION


def format_pod_document_uploaded_action() -> str:
    return POD_DOCUMENT_UPLOADED_ACTION


def format_pod_uploaded_manually_info() -> str:
    return POD_UPLOADED_MANUALLY_INFO


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


def format_pod_found_in_tms_info() -> str:
    return POD_FOUND_IN_TMS_INFO


def format_workflow_review_acknowledged_action() -> str:
    """ACTION text for portal acknowledge; used by ``WorkflowReviewService.acknowledge``."""
    return WORKFLOW_REVIEW_ACKNOWLEDGED_ACTION


def format_workflow_review_resolved_action() -> str:
    """ACTION text for portal resolve; used by ``WorkflowReviewService.resolve``."""
    return WORKFLOW_REVIEW_RESOLVED_ACTION


def format_tms_connection_timed_out_description() -> str:
    """EXCEPTION text when Turvo transient HTTP retries are exhausted."""
    return TMS_CONNECTION_TIMED_OUT_EXCEPTION
