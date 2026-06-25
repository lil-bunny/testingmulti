from __future__ import annotations

from app.services.routing_guide_lifecycle_service import RoutingGuideLifecycleService


def evaluate_reject_routing_guide(state):
    state.data["routing_guide_reason"] = "carrier_rejected"
    return state


def evaluate_timeout_routing_guide(state):
    state.data["routing_guide_reason"] = "carrier_timeout"
    return state


def advance_carrier_routing_guide(state):
    reason = str(state.data.get("routing_guide_reason") or "").strip()
    routing_guide_lifecycle_service = RoutingGuideLifecycleService()
    routing_guide_lifecycle_service.advance(state, reason=reason)
    return state
