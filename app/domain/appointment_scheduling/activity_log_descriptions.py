"""Human-readable activity log descriptions for ``appointment_scheduling``."""

from __future__ import annotations


def format_scheduling_decision_info(
    *,
    reference_number: str,
    pickup_date: str,
    delivery_date: str,
    delivery_weekday: str,
    decision_source: str,
) -> str:
    ref = (reference_number or "").strip() or "unknown"
    pickup = (pickup_date or "").strip() or "unknown"
    delivery = (delivery_date or "").strip() or "unknown"
    weekday = (delivery_weekday or "").strip() or "unknown"
    source = (decision_source or "").strip() or "unknown"
    return (
        f"Scheduling decision for {ref}: pickup {pickup}, "
        f"delivery {weekday} {delivery} (source={source})"
    )


def format_appointment_draft_created_action() -> str:
    return "Appointment draft email created"


def format_appointment_draft_teams_notification_action() -> str:
    return "Sent notification on Teams"


def format_appointment_email_sent_action() -> str:
    return "Appointment request email sent"


def format_customer_reply_llm_action(
    *,
    decision: str,
    reason: str,
    confidence: float,
) -> str:
    return (
        f"Customer reply classification: {decision} "
        f"(confidence={confidence:.2f}, {reason or 'no reason'})"
    )


def format_ascend_dropoff_updated_action(*, reference_number: str, appointment_start: str) -> str:
    ref = (reference_number or "").strip() or "unknown"
    return f"Ascend dropoff appointment updated for {ref} at {appointment_start}"


def format_ascend_dropoff_skipped_action(*, reference_number: str) -> str:
    ref = (reference_number or "").strip() or "unknown"
    return f"Ascend dropoff update skipped (Ascend writes disabled) for {ref}"


def format_turvo_delivery_updated_action(*, stop_name: str, start_time: str) -> str:
    stop = (stop_name or "").strip() or "unknown"
    return f"Turvo delivery appointment updated for {stop} at {start_time}"


def format_turvo_delivery_placeholder_action(*, stop_name: str, start_time: str) -> str:
    stop = (stop_name or "").strip() or "unknown"
    return f"Turvo delivery placeholder set for {stop} at {start_time}"


def format_ascend_pickup_updated_action(*, reference_number: str, start_time: str) -> str:
    ref = (reference_number or "").strip() or "unknown"
    return f"Ascend pickup appointment updated for {ref} at {start_time}"


def format_turvo_pickup_updated_action(*, stop_name: str, start_time: str) -> str:
    stop = (stop_name or "").strip() or "unknown"
    return f"Turvo pickup appointment updated for {stop} at {start_time}"


def format_appointment_confirmation_sent_action() -> str:
    return "Appointment confirmation reply sent"


def format_turvo_tendered_action(*, reference_number: str) -> str:
    ref = (reference_number or "").strip() or "unknown"
    return f"Turvo shipment status updated to Tendered for {ref}"
