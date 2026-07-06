"""Node: after successful reminder — map reminder_step to lifecycle sub_status + activity log."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_reminder_sent_action
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.load_tendering_lifecycle_guards import (
    delayed_workflow_step_skip_reason,
    skip_sub_statuses_from_state,
    stale_ftl_routing_guide_reminder,
)

logger = get_logger(__name__)


def update_reminder_status(state):
    """
    After a successful carrier-thread reminder: map ``reminder_step`` to lifecycle
    ``sub_status`` (``reminder_1_sent`` / ``reminder_2_sent``) and append activity log.

    On success: ``action`` (reminder sent narrative) then status/sub_status change in one transaction.

    When lifecycle is already terminal (e.g. ack won a race): record the action only;
    do not change status or sub_status.
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    run_id = str(state.execution_id or "").strip()
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

    if stale_ftl_routing_guide_reminder(state):
        logger.info(
            "update_reminder_status skipping stale routing-guide reminder lifecycle_id=%s",
            wl_id,
        )
        state.data["reminder_status_skipped"] = "stale_routing_guide_reminder"
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

    if not run_id:
        logger.warning(
            "update_reminder_status success path skipped: missing execution_id lifecycle_id=%s",
            wl_id,
        )
        return state

    new_sub = (
        StatusSubType.REMINDER_1_SENT
        if step == 1
        else StatusSubType.REMINDER_2_SENT
    )
    transition_meta: dict[str, Any] = {
        "reminder_step": step,
        "tender_id": state.data.get("tender_id"),
    }
    action_meta = dict(transition_meta)
    communication_id = str(state.data.get("communication_id") or "").strip() or None
    action_step = ActivityLogStep(
        activity_type=ActivityType.ACTION,
        description=format_reminder_sent_action(step=step),
        metadata=dict(action_meta),
        communication_id=communication_id,
    )

    workflow_lifecycle_service = WorkflowLifecycleService()
    prev = workflow_lifecycle_service.read_lifecycle_row_by_id(wl_id)
    skip = delayed_workflow_step_skip_reason(
        prev,
        skip_sub_statuses=skip_sub_statuses_from_state(state),
    )

    activity_log_service = ActivityLogService()
    if skip:
        logger.info(
            "update_reminder_status audit-only reminder action lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(action_step,),
            )
        )
        state.data["reminder_status_skipped"] = skip
        return state

    if not run_id:
        logger.warning(
            "update_reminder_status success path skipped: missing execution_id lifecycle_id=%s",
            wl_id,
        )
        return state

    communication_id = str(state.data.get("communication_id") or "").strip() or None

    current_status = status_type_from_db(prev.get("status")) if prev else None
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        transition_step = ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_sub_status=new_sub,
        )
    else:
        transition_step = ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
        )

    activity_log_service.record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_reminder_sent_action(step=step),
                    communication_id=communication_id,
                ),
                transition_step,
            ),
        )
    )

    state.data["reminder_sub_status"] = new_sub.value
    return state
