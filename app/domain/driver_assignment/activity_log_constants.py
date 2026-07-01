"""ACTION description templates for ``driver_assignment`` activity_logs rows."""

from __future__ import annotations

DRIVER_DETAILS_LLM_ACTION_TEMPLATE = (
    "Driver details LLM classified reply as {decision}{confidence_suffix}: {reason}"
)
DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE = "Driver assignment not started: {reason}"
DRIVER_ASSIGNMENT_CANCELLED_TENDERED_ACTION = (
    "Driver assignment cancelled — shipment tendered in Turvo"
)
DRIVER_ASSIGNMENT_CANCELLED_RATECON_SUPERSEDED_ACTION = (
    "Driver assignment cancelled — superseded by new inbound ratecon email"
)
DRIVER_REMINDER_SENT_TEMPLATE = "Driver reminder {step} sent"
DRIVER_DETAILS_PARTIAL_FOLLOW_UP_TEMPLATE = "Driver details partial follow-up sent"
DRIVER_NOT_FOUND_IN_TMS_TEMPLATE = "Driver not found in TMS"
DRIVER_AMBIGUOUS_IN_TMS_TEMPLATE = (
    "Multiple drivers found in TMS ({match_by}={match_value}, count={count})"
)
DRIVER_ASSIGNED_IN_TMS_ACTION = "Driver assigned to shipment in TMS"
DRIVER_ALREADY_ASSIGNED_IN_TMS_ACTION = (
    "Driver already assigned on shipment in TMS; assign skipped"
)
DRIVER_ASSIGN_TO_TMS_FAILED_TEMPLATE = "Driver assignment to TMS failed: {reason}"
DRIVER_CONFIRMATION_TRACKING_SENT_ACTION = (
    "Driver confirmation email sent (tracking customer)"
)
DRIVER_CONFIRMATION_DEFAULT_SENT_ACTION = "Driver confirmation email sent"
DRIVER_ESCALATION_SENT_ACTION = "Driver details escalated to internal Teams channel"
