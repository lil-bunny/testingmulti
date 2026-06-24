"""Ratecon tail node: enqueue driver_assignment on successful ratecon completion."""

from __future__ import annotations

from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService


def enqueue_driver_assignment_on_ratecon_complete(state):
    DriverAssignmentIngressService().try_enqueue_from_ratecon_state(state)
    return state
