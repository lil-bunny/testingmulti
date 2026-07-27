"""Appointment scheduling domain types."""

from app.domain.appointment_scheduling.constants import (
    APPOINTMENT_SCHEDULING_WORKFLOW,
)
from app.domain.appointment_scheduling.scheduling_reference import (
    is_diamond_scheduling_reference,
)

__all__ = [
    "APPOINTMENT_SCHEDULING_WORKFLOW",
    "is_diamond_scheduling_reference",
]
