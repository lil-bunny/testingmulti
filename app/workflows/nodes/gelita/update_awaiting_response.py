"""Node: first inbound carrier thread — persist thread, awaiting_response, activity log."""

from __future__ import annotations

import uuid

from app.core.logger import get_logger
from app.models.actor_type import ActorType
from app.models.status import StatusSubType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


def update_awaiting_response(state):
    """
    First inbound carrier thread:
    - persist thread id
    - transition to awaiting_response
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

    lifecycle_svc = WorkflowLifecycleService()

    row_before = lifecycle_svc.read_lifecycle_row_by_id(wl_id)

    if not row_before:
        logger.warning(
            "update_awaiting_response lifecycle not found id=%s",
            wl_id,
        )
        return state

    prev_sub_status = (
        StatusSubType(row_before["sub_status"])
        if row_before.get("sub_status")
        else None
    )

    if thread_id:
        lifecycle_svc.update_lifecycle_keys(
            lifecycle_id=wl_id,
            thread_id=thread_id,
        )

    updated = lifecycle_svc.update_lifecycle_sub_status(
        lifecycle_id=wl_id,
        new_sub_status=StatusSubType.AWAITING_RESPONSE,
    )

    row_after = lifecycle_svc.read_lifecycle_row_by_id(wl_id)

    next_sub_status = (
        StatusSubType(row_after["sub_status"])
        if row_after and row_after.get("sub_status")
        else None
    )

    if updated or thread_id:
        try:
            actor_id = str(uuid.uuid4())
            ActivityLogService().insert(
                tenant_id=tenant_id,
                actor_type=ActorType.SYSTEM.value,
                actor_id=actor_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=str(state.execution_id),
                activity_type="awaiting_response",
                description="Awaiting carrier acknowledgment on captured thread",
                from_sub_status=prev_sub_status,
                to_sub_status=next_sub_status,
                metadata=(
                    {"thread_id": thread_id}
                    if thread_id
                    else {}
                ),
            )

        except Exception:
            logger.exception(
                "update_awaiting_response activity log failed lifecycle_id=%s",
                wl_id,
            )

    return state
