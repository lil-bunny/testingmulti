"""Node: first inbound carrier email — set ``tender_sent_to_carrier`` sub_status."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def record_tender_sent_to_carrier(state):
    """
    First inbound carrier email on the tender thread:

    - set lifecycle ``sub_status`` to ``tender_sent_to_carrier`` (top-level stays ``processing``)
    - write activity log with ``communication_id`` from graph state when present
    """

    wl_id = str(
        state.data.get("workflow_lifecycle_id") or ""
    ).strip()

    tenant_id = (state.tenant_id or "").strip()

    if not wl_id or not tenant_id:
        logger.warning(
            "record_tender_sent_to_carrier missing workflow_lifecycle_id or tenant_id"
        )
        return state

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        actor_type=ActorType.SYSTEM
    )

    return state
