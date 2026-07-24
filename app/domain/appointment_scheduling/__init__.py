"""Appointment scheduling domain types."""

from app.domain.appointment_scheduling.constants import (
    APPOINTMENT_SCHEDULING_WORKFLOW,
    SCHEDULING_INGRESS_SKIP_REASONS,
)
from app.domain.appointment_scheduling.scheduling_reference import (
    is_diamond_scheduling_reference,
)

__all__ = [
    "APPOINTMENT_SCHEDULING_WORKFLOW",
    "SCHEDULING_INGRESS_SKIP_REASONS",
    "is_diamond_scheduling_reference",
]
