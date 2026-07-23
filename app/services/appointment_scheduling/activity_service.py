"""Activity log writes for ``appointment_scheduling`` workflow (thin facade)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.services.activity_log_service import ActivityLogService
from app.services.appointment_scheduling.activity_common import SchedulingActivityDeps
from app.services.appointment_scheduling.confirm_activity import ConfirmActivity
from app.services.appointment_scheduling.intake_activity import IntakeActivity
from app.services.appointment_scheduling.reply_activity import ReplyActivity
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService


class ActivityService:
    def __init__(
        self,
        *,
        activity_log_service: ActivityLogService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
        transition_service: LifecycleTransitionService | None = None,
    ) -> None:
        self._deps = SchedulingActivityDeps(
            lifecycle_service=lifecycle_service,
            transition_service=transition_service,
            activity_log_service=activity_log_service,
        )
        self._intake = IntakeActivity(self._deps)
        self._confirm = ConfirmActivity(self._deps)
        self._reply = ReplyActivity(self._deps)

    def record_started(self, state) -> None:
        self._intake.record_started(state)

    def record_decision(self, state) -> None:
        self._intake.record_decision(state)

    def record_draft_ready(
        self,
        state,
        *,
        email_draft: dict[str, Any],
        scheduling_payload: dict[str, Any],
    ) -> None:
        self._intake.record_draft_ready(
            state,
            email_draft=email_draft,
            scheduling_payload=scheduling_payload,
        )

    def record_draft_pending_review(self, state) -> None:
        self._intake.record_draft_pending_review(state)

    def record_draft_teams_notification(self, state) -> None:
        self._intake.record_draft_teams_notification(state)

    def record_confirm_email_sent(
        self,
        state,
        *,
        communication_id: str | None,
        actor_id: str | None,
    ) -> None:
        self._confirm.record_confirm_email_sent(
            state,
            communication_id=communication_id,
            actor_id=actor_id,
        )

    def record_awaiting_customer_reply(self, state) -> None:
        self._confirm.record_awaiting_customer_reply(state)

    def record_weekend_pickup_update(self, state, *, result: dict[str, Any]) -> None:
        self._confirm.record_weekend_pickup_update(state, result=result)

    def record_turvo_confirm_placeholder(self, state, *, result: dict[str, Any]) -> None:
        self._confirm.record_turvo_confirm_placeholder(state, result=result)

    def record_failed(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str | None,
        failure: SchedulingFailure,
    ) -> None:
        self._intake.record_failed(
            tenant_id=tenant_id,
            workflow_lifecycle_id=workflow_lifecycle_id,
            workflow_run_id=workflow_run_id,
            failure=failure,
        )

    def record_ascend_update(self, state) -> None:
        self._reply.record_ascend_update(state)

    def record_turvo_update(self, state) -> None:
        self._reply.record_turvo_update(state)

    def record_confirmation_sent(self, state) -> None:
        self._reply.record_confirmation_sent(state)

    def record_turvo_tendered(self, state) -> None:
        self._reply.record_turvo_tendered(state)

    def record_reply_completed(self, state) -> None:
        self._reply.record_reply_completed(state)

    def record_reply_rejected(self, state) -> None:
        self._reply.record_reply_rejected(state)


__all__ = ("ActivityService",)
