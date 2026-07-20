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


def format_appointment_email_sent_action() -> str:
    return "Appointment request email sent"


def format_appointment_scheduling_failed_action(*, reason: str) -> str:
    return f"Appointment scheduling failed: {(reason or '').strip() or 'unknown'}"
