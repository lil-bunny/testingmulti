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
TENDER_SENT_TO_VENDOR_ACTION = "Tender email sent to vendor"
CARRIER_ACK_LLM_ACTION_TEMPLATE = (
    "Carrier ack LLM classified reply as {decision}{confidence_suffix}: {reason}"
)
REMINDER_SENT_ACTION_TEMPLATE = "Reminder {step} sent to carrier"
ESCALATION_SENT_ACTION = "Tender escalated to internal recipients"
RATECON_RECEIVED_ACTION = "Ratecon email received"
RATECON_DOCUMENT_UPLOADED_ACTION = "Ratecon document uploaded to S3"
RATECON_DOCUMENT_UPLOAD_FAILED_ACTION = "Ratecon document upload failed"
RATECON_DOCUMENT_PROCESSED_ACTION = "Ratecon document processed"
RATECON_DOCUMENT_PROCESSING_FAILED_ACTION = "Ratecon document processing failed"
RATECON_DOCUMENT_PROCESSED_WITH_LLM_TEMPLATE = (
    "Ratecon document processed — LLM extraction{confidence_suffix}"
)
POD_STARTED_ACTION = "POD lifecycle started"
DRIVER_ASSIGNMENT_STARTED_ACTION = "Driver assignment started"
DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE = "Driver assignment not started: {reason}"
DRIVER_REMINDERS_SCHEDULED_ACTION = "Driver reminders scheduled"
POD_ESCALATION_SENT_ACTION = "POD request escalated to internal recipients"
POD_DOCUMENT_UPLOADED_ACTION = "POD document uploaded to S3"
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
POD_ALREADY_ON_TMS_ACTION = "POD already present on TMS; upload skipped"
POD_REVIEW_ACKNOWLEDGED_ACTION = "PoD review acknowledged"