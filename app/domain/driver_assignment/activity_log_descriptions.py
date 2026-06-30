"""Human-readable activity log descriptions for ``driver_assignment``."""

from __future__ import annotations

from app.domain.driver_assignment.activity_log_constants import (
    DRIVER_ALREADY_ASSIGNED_IN_TMS_ACTION,
    DRIVER_AMBIGUOUS_IN_TMS_TEMPLATE,
    DRIVER_ASSIGNED_IN_TMS_ACTION,
    DRIVER_ASSIGNMENT_CANCELLED_RATECON_SUPERSEDED_ACTION,
    DRIVER_ASSIGNMENT_CANCELLED_TENDERED_ACTION,
    DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE,
    DRIVER_ASSIGN_TO_TMS_FAILED_TEMPLATE,
    DRIVER_CONFIRMATION_DEFAULT_SENT_ACTION,
    DRIVER_CONFIRMATION_TRACKING_SENT_ACTION,
    DRIVER_CREATED_IN_TMS_ACTION,
    DRIVER_DETAILS_LLM_ACTION_TEMPLATE,
    DRIVER_DETAILS_PARTIAL_FOLLOW_UP_TEMPLATE,
    DRIVER_ESCALATION_SENT_ACTION,
    DRIVER_FOUND_IN_TMS_ACTION,
    DRIVER_NOT_FOUND_IN_TMS_TEMPLATE,
    DRIVER_REMINDER_SENT_TEMPLATE,
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


def format_driver_assignment_not_started_action(*, reason: str) -> str:
    return DRIVER_ASSIGNMENT_NOT_STARTED_TEMPLATE.format(reason=reason)


def format_driver_assignment_cancelled_tendered_action() -> str:
    return DRIVER_ASSIGNMENT_CANCELLED_TENDERED_ACTION


def format_driver_assignment_cancelled_ratecon_superseded_action() -> str:
    return DRIVER_ASSIGNMENT_CANCELLED_RATECON_SUPERSEDED_ACTION


def format_driver_reminder_sent_action(*, step: int | None = None) -> str:
    label = str(step) if step is not None else "?"
    return DRIVER_REMINDER_SENT_TEMPLATE.format(step=label)


def format_driver_details_partial_follow_up_action() -> str:
    return DRIVER_DETAILS_PARTIAL_FOLLOW_UP_TEMPLATE


def format_driver_found_in_tms_action() -> str:
    return DRIVER_FOUND_IN_TMS_ACTION


def format_driver_not_found_in_tms_action() -> str:
    return DRIVER_NOT_FOUND_IN_TMS_TEMPLATE


def format_driver_ambiguous_in_tms_action(
    *, match_by: str, match_value: str, count: int
) -> str:
    return DRIVER_AMBIGUOUS_IN_TMS_TEMPLATE.format(
        match_by=match_by,
        match_value=match_value,
        count=count,
    )


def format_driver_created_in_tms_action() -> str:
    return DRIVER_CREATED_IN_TMS_ACTION


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


def format_driver_escalation_sent_action() -> str:
    return DRIVER_ESCALATION_SENT_ACTION
