"""Activity log nodes for the ``pod_lifecycle`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_pod_escalation_sent_action,
    format_pod_started_action,
    format_reminder_sent_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_service import parse_reminders_for_workflow
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

logger = get_logger(__name__)


def _scope_ids(state) -> tuple[str, str, str] | None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def _pod_metadata(state) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    for key in ("shipment_id", "shipments_row_id", "thread_id", "load_id"):
        raw = state.data.get(key)
        if raw is not None and str(raw).strip():
            meta[key] = str(raw).strip()
    wl_id = state.data.get("workflow_lifecycle_id")
    if wl_id is not None and str(wl_id).strip():
        meta["workflow_lifecycle_id"] = str(wl_id).strip()
    return meta


def _communication_id(state) -> str | None:
    raw = state.data.get("communication_id")
    if raw is None:
        return None
    cid = str(raw).strip()
    return cid or None


def _sub_status_for_reminder_step(step: int) -> StatusSubType | None:
    mapping = {
        1: StatusSubType.REMINDER_1_SENT,
        2: StatusSubType.REMINDER_2_SENT,
        3: StatusSubType.REMINDER_3_SENT,
    }
    return mapping.get(step)


def _build_reminder_transition_step(
    *,
    current_status: StatusType | None,
    new_sub: StatusSubType,
    metadata: dict[str, Any],
) -> ActivityLogStep:
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_sub_status=new_sub,
            metadata=dict(metadata),
        )
    return ActivityLogStep(
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=to_status,
        to_sub_status=new_sub,
        metadata=dict(metadata),
    )


def _pod_skip_sub_statuses_from_state(state: Any) -> frozenset[str]:
    data = getattr(state, "data", None) or {}
    if not isinstance(data, dict):
        return frozenset()
    cfg = parse_reminders_for_workflow(data, "pod_lifecycle")
    if cfg is None:
        return frozenset()
    return frozenset(s.strip() for s in cfg.skip_sub_statuses if str(s).strip())


def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    status = status_type_from_db(row.get("status"))
    sub = sub_status_type_from_db(row.get("sub_status"))
    if status not in (None, StatusType.NONE):
        return True
    if sub not in (None, StatusSubType.NONE, StatusSubType.POD_STARTED):
        return True
    if sub == StatusSubType.POD_STARTED:
        return True
    return False


def record_pod_started_activity(state):
    """
    Log POD lifecycle started after reminders are scheduled on ``route_completed``.

    ACTION + STATUS_CHANGE: ``none/processing``, ``none/pod_started``.
    """
    if not state.data.get("reminders_scheduled"):
        logger.info(
            "record_pod_started_activity skipping (reminders not scheduled) lifecycle_id=%s",
            state.data.get("workflow_lifecycle_id"),
        )
        return state

    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_started_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    if _lifecycle_already_started(row):
        logger.info(
            "record_pod_started_activity skipping already started lifecycle_id=%s",
            wl_id,
        )
        return state

    meta = _pod_metadata(state)
    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_started_action(),
                    metadata=meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PROCESSING,
                    to_sub_status=StatusSubType.POD_STARTED,
                    from_status=StatusType.NONE,
                    from_sub_status=StatusSubType.NONE,
                    metadata=meta,
                ),
            ),
        )
    )
    return state


def record_pod_reminder_activity(state):
    """
    After successful POD reminder email: map ``reminder_step`` to lifecycle sub_status
    and append activity log (steps 1–3).
    """
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id:
        logger.warning(
            "record_pod_reminder_activity missing workflow_lifecycle_id or tenant_id"
        )
        return state

    if not state.data.get("pod_reminder_sent"):
        logger.info(
            "record_pod_reminder_activity skipping (reminder not sent) lifecycle_id=%s",
            wl_id,
        )
        state.data["pod_reminder_status_skipped"] = "reminder_not_sent"
        return state

    raw_step = state.data.get("reminder_step")
    try:
        step = int(raw_step) if raw_step is not None else None
    except (TypeError, ValueError):
        step = None
    if step not in (1, 2, 3):
        logger.warning(
            "record_pod_reminder_activity invalid reminder_step=%r lifecycle_id=%s",
            raw_step,
            wl_id,
        )
        state.data["pod_reminder_status_error"] = "invalid_reminder_step"
        return state

    new_sub = _sub_status_for_reminder_step(step)
    assert new_sub is not None

    lifecycle_service = WorkflowLifecycleService()
    prev = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    skip = delayed_workflow_step_skip_reason(
        prev,
        skip_sub_statuses=_pod_skip_sub_statuses_from_state(state),
    )
    if skip:
        logger.info(
            "record_pod_reminder_activity skipping lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["pod_reminder_status_skipped"] = skip
        return state

    if not run_id:
        logger.warning(
            "record_pod_reminder_activity success path skipped: missing execution_id lifecycle_id=%s",
            wl_id,
        )
        return state

    transition_meta: dict[str, Any] = {
        "reminder_step": step,
        **_pod_metadata(state),
    }
    communication_id = _communication_id(state)

    current_status = status_type_from_db(prev.get("status")) if prev else None
    transition_step = _build_reminder_transition_step(
        current_status=current_status,
        new_sub=new_sub,
        metadata=transition_meta,
    )

    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_reminder_sent_action(step=step),
                    metadata=dict(transition_meta),
                    communication_id=communication_id,
                ),
                transition_step,
            ),
        )
    )

    state.data["pod_reminder_sub_status"] = new_sub.value
    return state


def record_pod_escalation_activity(state):
    """
    Log POD escalation sub_status (no email send).

    Callable from a future ``escalation_due`` graph path; not wired in ``workflow_configs`` yet.
    """
    scope = _scope_ids(state)
    if scope is None:
        logger.warning(
            "record_pod_escalation_activity skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(state.data.get("workflow_lifecycle_id")),
            bool(state.tenant_id or state.data.get("tenant_id")),
            bool(state.execution_id),
        )
        return state

    wl_id, tenant_id, run_id = scope
    lifecycle_service = WorkflowLifecycleService()
    row = lifecycle_service.read_lifecycle_row_by_id(wl_id)
    skip = delayed_workflow_step_skip_reason(
        row,
        skip_sub_statuses=_pod_skip_sub_statuses_from_state(state),
    )
    if skip:
        logger.info(
            "record_pod_escalation_activity skipping lifecycle_id=%s reason=%s",
            wl_id,
            skip,
        )
        state.data["pod_escalation_skipped"] = skip
        return state

    meta = _pod_metadata(state)
    ActivityLogService().record_sequence(
        ActivityLogSequence(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            steps=(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_pod_escalation_sent_action(),
                    metadata=meta,
                ),
                ActivityLogStep(
                    activity_type=ActivityType.SUB_STATUS_CHANGE,
                    to_sub_status=StatusSubType.ESCALATED,
                    from_sub_status=StatusSubType.REMINDER_3_SENT,
                    metadata=meta,
                ),
            ),
        )
    )
    state.data["pod_escalation_sub_status"] = StatusSubType.ESCALATED.value
    return state
