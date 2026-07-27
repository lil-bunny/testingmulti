from __future__ import annotations

from app.core.logger import get_logger
from app.domain.gelita.shipper_email import (
    is_gelita_shipper_email,
    reply_from_email_from_state_data,
)
from app.services.routing_guide_lifecycle_service import RoutingGuideLifecycleService

logger = get_logger(__name__)


def evaluate_reject_routing_guide(state):
    """
    Mark reject reason for routing-guide router.

    Shipper ``@gelita.com`` rejects are terminal (no next-carrier advance / escalate).
    """
    from_email = reply_from_email_from_state_data(state.data)
    if is_gelita_shipper_email(from_email):
        state.data["routing_guide_shipper_domain_reject"] = True
        state.data["routing_guide_reason"] = "shipper_rejected"
        logger.info(
            "routing_guide shipper-domain reject is terminal from=%r tender_id=%s",
            from_email,
            state.data.get("tender_id"),
        )
        return state

    state.data["routing_guide_reason"] = "carrier_rejected"
    return state


def evaluate_timeout_routing_guide(state):
    state.data["routing_guide_reason"] = "carrier_timeout"
    return state


def advance_carrier_routing_guide(state):
    reason = str(state.data.get("routing_guide_reason") or "").strip()
    routing_guide_lifecycle_service = RoutingGuideLifecycleService()
    routing_guide_lifecycle_service.advance(state, reason=reason)
    state.data["routing_guide_failover"] = True
    return state
