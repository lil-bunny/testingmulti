"""Appointment scheduling ingress result types."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.appointment_scheduling.ingress_constants import APPOINTMENT_SCHEDULING_WORKFLOW

__all__ = ["APPOINTMENT_SCHEDULING_WORKFLOW", "IngressHandleResult"]


@dataclass(frozen=True)
class IngressHandleResult:
    """Outcome of Turvo SHIPMENT_UPDATE scheduling ingress."""

    handled: bool
    enqueued: bool = False
    skip_reason: str | None = None
    execution_id: str | None = None
