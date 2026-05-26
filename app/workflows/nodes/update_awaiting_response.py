"""Node: first inbound carrier thread — persist thread, awaiting_response, activity log."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def update_awaiting_response(state):
    """
    First inbound carrier thread:
    - persist thread id
    - transition to tender_sent_to_carrier
    - write activity log
    """

    wl_id = str(
        state.data.get("workflow_lifecycle_id") or ""
    ).strip()

    tenant_id = (state.tenant_id or "").strip()

    thread_id = str(
        state.data.get("thread_id")
        or state.data.get("email_thread_id")
        or ""
    ).strip()

    if not wl_id or not tenant_id:
        logger.warning(
            "update_awaiting_response missing workflow_lifecycle_id or tenant_id"
        )
        return state

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_sub_status=StatusSubType.TENDER_SENT_TO_CARRIER,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        description="Awaiting carrier acknowledgment on captured thread",
        actor_type=ActorType.SYSTEM,
        email_thread_id=thread_id or None,
        metadata={"thread_id": thread_id} if thread_id else {},
    )

    return state
