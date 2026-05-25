"""Node: persist lifecycle + activity log after ``send_tender_email``."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def log_tender_activity(state):
    """
    Persist lifecycle + activity log after ``send_tender_email`` (success or failure).
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    if not wl_id or not tenant_id:
        logger.warning("log_tender_activity missing workflow_lifecycle_id or tenant_id")
        return state

    lifecycle_transition_service = LifecycleTransitionService()
    sent = bool(state.data.get("tender_email_sent"))
    if sent:
        lifecycle_transition_service.apply_from_state(
            state,
            to_status=StatusType.PENDING_REVIEW,
            to_sub_status=StatusSubType.TENDER_SENT_TO_TENANT,
            activity_type=ActivityType.STATUS_CHANGE,
            description="Tender email sent to vendor",
            actor_type=ActorType.SYSTEM,
            metadata={"tender_id": state.data.get("tender_id")},
        )
    else:
        err = state.data.get("tender_email_error") or "tender_email_not_sent"
        lifecycle_transition_service.apply_from_state(
            state,
            to_status=StatusType.FAILED,
            activity_type=ActivityType.STATUS_CHANGE,
            description=str(err),
            actor_type=ActorType.SYSTEM,
            metadata={"error": str(err)},
        )
    return state
