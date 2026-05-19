"""Node: after successful reminder — map reminder_step to lifecycle sub_status + activity log."""

from __future__ import annotations

from app.core.logger import get_logger
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.workflows.nodes.gelita.load_tendering_helpers import (
    status_type_from_db,
    sub_status_type_from_db,
)

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
    activity_type = "reminder_1_sent" if step == 1 else "reminder_2_sent"
    message = (
        "Tender reminder 1 sent on carrier thread"
        if step == 1
        else "Tender reminder 2 sent on carrier thread"
    )

    lifecycle_svc = WorkflowLifecycleService()
    prev = lifecycle_svc.read_lifecycle_row_by_id(wl_id)
    if not prev:
        logger.warning("update_reminder_status lifecycle not found id=%s", wl_id)
        state.data["reminder_status_error"] = "lifecycle_not_found"
        return state

    prev_status = status_type_from_db(prev.get("status"))
    prev_sub = sub_status_type_from_db(prev.get("sub_status"))

    if prev_status == StatusType.COMPLETED:
        logger.info(
            "update_reminder_status skipping: lifecycle already completed lifecycle_id=%s",
            wl_id,
        )
        state.data["reminder_status_skipped"] = "lifecycle_already_completed"
        return state

    lifecycle_svc.update_lifecycle_status(
        lifecycle_id=wl_id,
        sub_status=new_sub,
    )

    try:
        ActivityLogService().insert(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=str(state.execution_id),
            activity_type=activity_type,
            description=message,
            from_status=prev_status,
            to_status=prev_status,
            from_sub_status=prev_sub,
            to_sub_status=new_sub,
            metadata={
                "reminder_step": step,
                "tender_id": state.data.get("tender_id"),
            },
        )
    except Exception:
        logger.exception(
            "update_reminder_status activity log failed lifecycle_id=%s",
            wl_id,
        )

    state.data["reminder_sub_status"] = new_sub.value
    return state
