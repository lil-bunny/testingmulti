"""POD pipeline activity logging (started, reminders, extraction)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_pod_escalation_sent_action,
    format_pod_extraction_processed_action,
    format_reminder_sent_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.pod_lifecycle.activity_metadata import (
    extraction_action_metadata,
    reminder_action_metadata,
)
from app.domain.pod_lifecycle.guards import (
    POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,
    pod_analysis_stored_from_state,
    pod_reminder_skip_sub_statuses,
    should_skip_idempotent_pod_activity_log,
)
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

if TYPE_CHECKING:
    from app.domain.state import WorkflowState

logger = get_logger(__name__)


def _scope_ids(state: WorkflowState) -> tuple[str, str, str] | None:
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    run_id = str(state.execution_id or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return None
    return wl_id, tenant_id, run_id


def _communication_id(state: WorkflowState) -> str | None:
    raw = state.data.get("communication_id")
    if raw is None:
        return None
    cid = str(raw).strip()
    return cid or None


def _analysis_success(state: WorkflowState) -> bool:
    return pod_analysis_stored_from_state(state.data)


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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
) -> ActivityLogStep:
    to_status = StatusType.PENDING_REVIEW
    if current_status == to_status:
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
            metadata=None,
        )
    return ActivityLogStep(
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=to_status,
        to_sub_status=new_sub,
        metadata=None,
    )


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


class PodPipelineActivityService:
    """Record POD pipeline activity rows (started through ratecon validation)."""

    def __init__(
        self,
        *,
        activity_log_service: ActivityLogService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._activity_log_service = activity_log_service or ActivityLogService()
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()

    def record_started_from_state(self, state: WorkflowState) -> None:
        if not state.data.get("reminders_scheduled"):
            logger.info(
                "PodPipelineActivityService.started skipping (reminders not scheduled) lifecycle_id=%s",
                state.data.get("workflow_lifecycle_id"),
            )
            return

        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "PodPipelineActivityService.started skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)
        if _lifecycle_already_started(row):
            logger.info(
                "PodPipelineActivityService.started skipping already started lifecycle_id=%s",
                wl_id,
            )
            return

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.PROCESSING,
                        to_sub_status=StatusSubType.POD_STARTED,
                        from_status=StatusType.NONE,
                        from_sub_status=StatusSubType.NONE,
                        metadata=None,
                    ),
                ),
            )
        )

    def record_reminder_from_state(self, state: WorkflowState) -> None:
        wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
        run_id = str(state.execution_id or "").strip()

        if not wl_id or not tenant_id:
            logger.warning(
                "PodPipelineActivityService.reminder missing workflow_lifecycle_id or tenant_id"
            )
            return

        if not state.data.get("pod_reminder_sent"):
            logger.info(
                "PodPipelineActivityService.reminder skipping (reminder not sent) lifecycle_id=%s",
                wl_id,
            )
            state.data["pod_reminder_status_skipped"] = "reminder_not_sent"
            return

        raw_step = state.data.get("reminder_step")
        try:
            step = int(raw_step) if raw_step is not None else None
        except (TypeError, ValueError):
            step = None
        if step not in (1, 2, 3):
            logger.warning(
                "PodPipelineActivityService.reminder invalid reminder_step=%r lifecycle_id=%s",
                raw_step,
                wl_id,
            )
            state.data["pod_reminder_status_error"] = "invalid_reminder_step"
            return

        new_sub = _sub_status_for_reminder_step(step)
        assert new_sub is not None

        prev = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)
        skip = delayed_workflow_step_skip_reason(
            prev,
            skip_sub_statuses=pod_reminder_skip_sub_statuses(state.data),
        )
        if skip:
            logger.info(
                "PodPipelineActivityService.reminder skipping lifecycle_id=%s reason=%s",
                wl_id,
                skip,
            )
            state.data["pod_reminder_status_skipped"] = skip
            return

        if not run_id:
            logger.warning(
                "PodPipelineActivityService.reminder success path skipped: missing execution_id lifecycle_id=%s",
                wl_id,
            )
            return

        action_meta = reminder_action_metadata(step)
        communication_id = _communication_id(state)
        current_status = status_type_from_db(prev.get("status")) if prev else None
        transition_step = _build_reminder_transition_step(
            current_status=current_status,
            new_sub=new_sub,
        )

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_reminder_sent_action(step=step),
                        metadata=action_meta,
                        communication_id=communication_id,
                    ),
                    transition_step,
                ),
            )
        )

        state.data["pod_reminder_sub_status"] = new_sub.value

    def record_escalation_from_state(self, state: WorkflowState) -> None:
        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "PodPipelineActivityService.escalation skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)
        skip = delayed_workflow_step_skip_reason(
            row,
            skip_sub_statuses=pod_reminder_skip_sub_statuses(state.data),
        )
        if skip:
            logger.info(
                "PodPipelineActivityService.escalation skipping lifecycle_id=%s reason=%s",
                wl_id,
                skip,
            )
            state.data["pod_escalation_skipped"] = skip
            return

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_pod_escalation_sent_action(),
                        metadata=None,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.ESCALATED,
                        from_sub_status=StatusSubType.REMINDER_3_SENT,
                        metadata=None,
                    ),
                ),
            )
        )
        state.data["pod_escalation_sub_status"] = StatusSubType.ESCALATED.value

    def record_extraction_from_state(self, state: WorkflowState) -> None:
        scope = _scope_ids(state)
        if scope is None:
            logger.warning(
                "PodPipelineActivityService.extraction skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        if not _analysis_success(state):
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)
        if should_skip_idempotent_pod_activity_log(
            state.data,
            row,
            done_sub_statuses=POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,
        ):
            logger.info(
                "PodPipelineActivityService.extraction skipping already processed lifecycle_id=%s",
                wl_id,
            )
            return

        pod_results = state.data.get("pod_analysis_results") or {}
        if not isinstance(pod_results, dict):
            pod_results = {}
        confidence = _float_or_none(pod_results.get("confidence_score"))
        action_meta = extraction_action_metadata(state.data.get("pod_analysis_id"))

        self._activity_log_service.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_pod_extraction_processed_action(
                            confidence=confidence,
                        ),
                        metadata=action_meta,
                    ),
                ),
            )
        )
