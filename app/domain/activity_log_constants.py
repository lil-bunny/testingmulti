"""Templates and ACTION descriptions for activity_logs rows."""

from __future__ import annotations

# Transition description templates (status_change / sub_status_change)

STATUS_CHANGE_DESCRIPTION_TEMPLATE = (
    "Status changed from {from_status} to {to_status}"
)
SUB_STATUS_CHANGE_DESCRIPTION_TEMPLATE = (
    "Sub-status changed from {from_sub_status} to {to_sub_status}"
)

# ACTION description templates

TENDER_CREATED_ACTION_TEMPLATE = "Tender {order_number} created for {customer_name}"
TENDER_SENT_TO_TENANT_ACTION = "Tender email sent to Shipper"
CARRIER_ACK_LLM_ACTION_TEMPLATE = (
    "Carrier ack LLM classified reply as {decision}{confidence_suffix}: {reason}"
)
AUTO_REPLY_ACK_SKIPPED_ACTION = "Carrier acknowledge skipped for automatic reply"
REMINDER_SENT_ACTION_TEMPLATE = "Reminder {step} sent to carrier"
ESCALATION_SENT_ACTION = "Tender escalated to internal recipients"
RATECON_RECEIVED_ACTION = "Ratecon email received"
RATECON_SUPERSEDED_ACTION = (
    "Ratecon cancelled — superseded by new inbound ratecon email"
)
RATECON_DOCUMENT_UPLOADED_ACTION = "Ratecon document uploaded to S3"
RATECON_DOCUMENT_UPLOAD_FAILED_ACTION = "Ratecon document upload failed"
RATECON_DOCUMENT_PROCESSED_ACTION = "Ratecon document processed"
RATECON_DOCUMENT_PROCESSING_FAILED_ACTION = "Ratecon document processing failed"
RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE = (
    "Ratecon document processed — LLM extraction{confidence_suffix}"
)
POD_ESCALATION_SENT_ACTION = "POD request escalated to internal recipients"
POD_DOCUMENT_UPLOADED_ACTION = "POD document uploaded to S3"
POD_UPLOADED_MANUALLY_INFO = "POD uploaded manually"
POD_DOCUMENT_UPLOAD_FAILED_ACTION = "POD document upload failed"
POD_DOCUMENT_PROCESSED_ACTION = "POD document processed"
POD_DOCUMENT_PROCESSING_FAILED_ACTION = "POD document processing failed"
POD_EXTRACTION_PROCESSED_TEMPLATE = (
    "POD document processed — LLM extraction{confidence_suffix}"
)
POD_VS_RATECON_VALIDATED_TEMPLATE = (
    "POD validated against ratecon{confidence_suffix} ({status})"
)
POD_VS_RATECON_VALIDATION_SKIPPED_TEMPLATE = (
    "POD vs ratecon validation skipped ({reason})"
)
POD_VS_RATECON_VALIDATION_FAILED_ACTION = "POD vs ratecon validation failed"
POD_UPLOADED_TO_TMS_ACTION = "POD document uploaded to TMS"
POD_UPLOAD_TO_TMS_FAILED_ACTION = "POD upload to TMS failed"
POD_FOUND_IN_TMS_INFO = "Pod found in TMS"
WORKFLOW_REVIEW_ACKNOWLEDGED_ACTION = "Workflow review acknowledged"
WORKFLOW_REVIEW_RESOLVED_ACTION = "Workflow review resolved"
TMS_CONNECTION_TIMED_OUT_EXCEPTION = "TMS connection timed out"
