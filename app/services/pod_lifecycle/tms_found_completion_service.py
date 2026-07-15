"""Complete POD lifecycle when Turvo already has POD on ``reminder_due``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_pod_found_in_tms_info
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.pod_lifecycle.tms_upload_activity import (
    pod_uploaded_to_tms_completion_step,
    scope_from_lifecycle_row,
)
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService

if TYPE_CHECKING:
    from app.domain.state import WorkflowState

logger = get_logger(__name__)


@dataclass(frozen=True)
class PodTmsFoundCompletionResult:
    completed: bool = False
    already_terminal: bool = False
    reminders_cancelled: int = 0
    skip_reason: str | None = None


class PodLifecycleTmsFoundCompletionService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        activity_log_service: ActivityLogService | None = None,
        reminder_cancel_service: WorkflowReminderCancelService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._activity = activity_log_service or ActivityLogService()
        self._reminder_cancel = reminder_cancel_service or WorkflowReminderCancelService()

    def complete_on_reminder_from_state(
        self,
        state: WorkflowState,
    ) -> PodTmsFoundCompletionResult:
        data = state.data
        if str(data.get("event_type") or "").strip() != "reminder_due":
            return PodTmsFoundCompletionResult(skip_reason="not_reminder_due")
        if not data.get("pod_exists"):
            return PodTmsFoundCompletionResult(skip_reason="pod_not_found")

        wl_id = str(data.get("workflow_lifecycle_id") or "").strip()
        tenant_id = str(state.tenant_id or data.get("tenant_id") or "").strip()
        run_id = str(state.execution_id or data.get("execution_id") or "").strip()
        if not wl_id or not tenant_id or not run_id:
            logger.warning(
                "PodLifecycleTmsFoundCompletionService skipped missing ids "
                "lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(wl_id),
                bool(tenant_id),
                bool(run_id),
            )
            return PodTmsFoundCompletionResult(skip_reason="missing_ids")

        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        if not row:
            logger.warning(
                "PodLifecycleTmsFoundCompletionService lifecycle not found id=%s",
                wl_id,
            )
            return PodTmsFoundCompletionResult(skip_reason="lifecycle_not_found")

        already_terminal = self._is_already_terminal(row)
        if not already_terminal:
            scope = scope_from_lifecycle_row(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                lifecycle_row=row,
                shipments_row_id=data.get("shipments_row_id"),
            )
            steps: list[ActivityLogStep] = [
                ActivityLogStep(
                    activity_type=ActivityType.INFO,
                    description=format_pod_found_in_tms_info(),
                    metadata=None,
                ),
            ]
            transition = pod_uploaded_to_tms_completion_step(scope=scope)
            if transition is not None:
                steps.append(transition)
            self._activity.record_sequence(
                ActivityLogSequence(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    actor_type=ActorType.SYSTEM,
                    actor_id=None,
                    steps=tuple(steps),
                )
            )

        revoked = self._reminder_cancel.cancel_all(lifecycle_id=wl_id)
        self._patch_state(
            data,
            completed=True,
            already_terminal=already_terminal,
            reminders_cancelled=revoked,
        )
        return PodTmsFoundCompletionResult(
            completed=True,
            already_terminal=already_terminal,
            reminders_cancelled=revoked,
        )

    @staticmethod
    def _is_already_terminal(row: dict[str, Any]) -> bool:
        status = status_type_from_db(row.get("status"))
        sub = sub_status_type_from_db(row.get("sub_status"))
        return (
            status == StatusType.COMPLETED
            and sub == StatusSubType.UPLOADED_TO_TMS
        )

    @staticmethod
    def _patch_state(
        data: dict[str, Any],
        *,
        completed: bool,
        already_terminal: bool,
        reminders_cancelled: int,
    ) -> None:
        data["pod_found_in_tms_completed"] = completed
        data["pod_found_in_tms_already_terminal"] = already_terminal
        data["pod_reminders_cancelled"] = reminders_cancelled > 0
        data["pod_tms_upload_outcome"] = "skipped"
