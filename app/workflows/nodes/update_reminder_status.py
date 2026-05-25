"""Node: after successful reminder — map reminder_step to lifecycle sub_status + activity log."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.status_parsing import status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


def update_reminder_status(state):
    """
    After a successful carrier-thread reminder: map ``reminder_step`` to lifecycle
    ``sub_status`` (``reminder_1_sent`` / ``reminder_2_sent``) and append activity log.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    if not wl_id or not tenant_id:
        logger.warning(
            "update_reminder_status missing workflow_lifecycle_id or tenant_id"
        )
        return state

    if not state.data.get("tender_reminder_sent"):
        logger.info(
            "update_reminder_status skipping DB update (reminder not sent) lifecycle_id=%s",
            wl_id,
        )
        state.data["reminder_status_skipped"] = "reminder_not_sent"
        return state

    raw_step = state.data.get("reminder_step")
    try:
        step = int(raw_step) if raw_step is not None else None
    except (TypeError, ValueError):
        step = None
    if step not in (1, 2):
        logger.warning(
            "update_reminder_status invalid reminder_step=%r lifecycle_id=%s",
            raw_step,
            wl_id,
        )
        state.data["reminder_status_error"] = "invalid_reminder_step"
        return state

    new_sub = (
        StatusSubType.REMINDER_1_SENT
        if step == 1
        else StatusSubType.REMINDER_2_SENT
    )
    message = (
        "Tender reminder 1 sent on carrier thread"
        if step == 1
        else "Tender reminder 2 sent on carrier thread"
    )

    workflow_lifecycle_service = WorkflowLifecycleService()
    prev = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if not prev:
        logger.warning("update_reminder_status lifecycle not found id=%s", wl_id)
        state.data["reminder_status_error"] = "lifecycle_not_found"
        return state

    if status_type_from_db(prev.get("status")) == StatusType.COMPLETED:
        logger.info(
            "update_reminder_status skipping: lifecycle already completed lifecycle_id=%s",
            wl_id,
        )
        state.data["reminder_status_skipped"] = "lifecycle_already_completed"
        return state

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        to_sub_status=new_sub,
        activity_type=ActivityType.SUB_STATUS_CHANGE,
        description=message,
        actor_type=ActorType.SYSTEM,
        metadata={
            "reminder_step": step,
            "tender_id": state.data.get("tender_id"),
        },
    )

    state.data["reminder_sub_status"] = new_sub.value
    return state
