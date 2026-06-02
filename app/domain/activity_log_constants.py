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
