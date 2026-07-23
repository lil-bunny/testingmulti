"""Activity log writes for ``appointment_scheduling`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep, ActivityLogWrite
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_confirmation_sent_action,
    format_appointment_draft_created_action,
    format_appointment_draft_teams_notification_action,
    format_appointment_email_sent_action,
    format_ascend_dropoff_skipped_action,
    format_ascend_dropoff_updated_action,
    format_scheduling_decision_info,
    format_turvo_delivery_updated_action,
    format_turvo_tendered_action,
)
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


class AppointmentSchedulingActivityService:
    def __init__(
        self,
        *,
        activity_log_service: ActivityLogService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._activity = activity_log_service or ActivityLogService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    @staticmethod
    def _scope_ids(state) -> tuple[str, str, str] | None:
        wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
        run_id = str(state.execution_id or "").strip()
        if not wl_id or not tenant_id or not run_id:
            return None
        return wl_id, tenant_id, run_id

    @staticmethod
    def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
        if not row:
            return False
        status = status_type_from_db(row.get("status"))
        return status not in (None, StatusType.NONE)

    @staticmethod
    def _build_sub_status_transition_step(
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
            )
        return ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
        )

    def record_started(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            logger.warning(
                "record_appointment_scheduling_started skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        if self._lifecycle_already_started(row):
            logger.info(
                "record_appointment_scheduling_started skipping already started lifecycle_id=%s",
                wl_id,
            )
            return

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=StatusType.NONE,
                        from_sub_status=StatusSubType.NONE,
                        to_status=StatusType.PROCESSING,
                        to_sub_status=StatusSubType.APPOINTMENT_SCHEDULING_STARTED,
                    ),
                ),
            )
        )

    def record_decision(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        decision = state.data.get("llm_scheduling_decision") or {}
        if not isinstance(decision, dict):
            decision = {}

        reference_number = str(state.data.get("reference_number") or "")
        selected_pickup_date = str(decision.get("selected_pickup_date") or "")
        calculated_delivery_date = str(decision.get("calculated_delivery_date") or "")
        calculated_delivery_weekday = str(
            decision.get("calculated_delivery_weekday") or ""
        )

        description = format_scheduling_decision_info(
            reference_number=reference_number,
            pickup_date=selected_pickup_date,
            delivery_date=calculated_delivery_date,
            delivery_weekday=calculated_delivery_weekday,
            decision_source="llm",
        )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=description,
                    ),
                ),
            )
        )

    def record_draft_ready(
        self,
        state,
        *,
        email_draft: dict[str, Any],
        scheduling_payload: dict[str, Any],
    ) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_draft_created_action(),
                    ),
                ),
            )
        )

    def record_draft_pending_review(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PROCESSING,
                        from_sub_status=from_sub or StatusSubType.APPOINTMENT_SCHEDULING_STARTED,
                        to_status=StatusType.PENDING_REVIEW,
                        to_sub_status=StatusSubType.APPOINTMENT_DRAFT_CREATED,
                    ),
                ),
            )
        )

    def record_draft_teams_notification(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_draft_teams_notification_action(),
                    ),
                ),
            )
        )

    def record_confirm_email_sent(
        self,
        state,
        *,
        communication_id: str | None,
        actor_id: str | None,
    ) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        current_sub = sub_status_type_from_db(row.get("sub_status")) if row else None
        if current_sub == StatusSubType.AWAITING_CUSTOMER_REPLY:
            return

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                actor_type=ActorType.USER,
                actor_id=actor_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_email_sent_action(),
                        communication_id=communication_id,
                    ),
                ),
            )
        )

    def record_awaiting_customer_reply(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        current_status = status_type_from_db(row.get("status")) if row else None
        current_sub = sub_status_type_from_db(row.get("sub_status")) if row else None
        if current_sub == StatusSubType.AWAITING_CUSTOMER_REPLY:
            return

        transition_step = self._build_sub_status_transition_step(
            current_status=current_status,
            new_sub=StatusSubType.AWAITING_CUSTOMER_REPLY,
        )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(transition_step,),
            )
        )

    def record_weekend_pickup_update(self, state, *, result: dict[str, Any]) -> None:
        if not isinstance(result, dict) or result.get("skipped"):
            return
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        from app.domain.appointment_scheduling.activity_log_descriptions import (
            format_ascend_pickup_updated_action,
            format_turvo_pickup_updated_action,
        )

        steps: list[ActivityLogStep] = []
        if result.get("ascend_updated"):
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_ascend_pickup_updated_action(
                        reference_number=str(state.data.get("reference_number") or ""),
                        start_time=str(result.get("turvo_pickup_start_time") or ""),
                    ),
                )
            )
        if result.get("turvo_updated"):
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_turvo_pickup_updated_action(
                        stop_name=str(result.get("pickup_stop_name") or ""),
                        start_time=str(result.get("turvo_pickup_start_time") or ""),
                    ),
                )
            )
        if not steps:
            return
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=tuple(steps),
            )
        )

    def record_turvo_confirm_placeholder(self, state, *, result: dict[str, Any]) -> None:
        scope = self._scope_ids(state)
        if scope is None or not isinstance(result, dict):
            return
        from app.domain.appointment_scheduling.activity_log_descriptions import (
            format_turvo_delivery_placeholder_action,
        )

        wl_id, tenant_id, run_id = scope
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_turvo_delivery_placeholder_action(
                            stop_name=str(result.get("stop_name") or ""),
                            start_time=str(result.get("start_time") or ""),
                        ),
                    ),
                ),
            )
        )

    def _record_catalog_exception(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str,
        failure: SchedulingFailure,
    ) -> None:
        metadata = {
            "error": failure.code,
            "error_category": failure.category.value,
            "error_description": failure.message,
        }
        self._activity.record_exception(
            ActivityLogWrite(
                tenant_id=tenant_id,
                workflow_lifecycle_id=workflow_lifecycle_id,
                workflow_run_id=workflow_run_id,
                description=failure.message,
                metadata=metadata,
                actor_type=ActorType.SYSTEM,
            )
        )

    def record_failed(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str | None,
        failure: SchedulingFailure,
    ) -> None:
        wl_id = str(workflow_lifecycle_id or "").strip()
        tenant = str(tenant_id or "").strip()
        run_id = str(workflow_run_id or "").strip() or None
        if not wl_id or not tenant or not run_id:
            logger.warning(
                "record_appointment_scheduling_failed skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(wl_id),
                bool(tenant),
                bool(run_id),
            )
            return

        self._record_catalog_exception(
            tenant_id=tenant,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            failure=failure,
        )

        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PROCESSING,
                        from_sub_status=from_sub or StatusSubType.NONE,
                        to_status=StatusType.PENDING_REVIEW,
                        to_sub_status=StatusSubType.NONE,
                    ),
                ),
            )
        )

    def record_ascend_update(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        result = state.data.get("ascend_update_result") or {}
        if not isinstance(result, dict):
            result = {}
        reference = str(state.data.get("reference_number") or "").strip()
        dry_run = bool(result.get("dry_run"))
        skipped = bool(result.get("skipped"))
        ok = bool(result.get("ok"))
        extraction = state.data.get("customer_reply_extraction") or {}
        appointment_start = str(
            (extraction.get("appointment_start_iso") if isinstance(extraction, dict) else None)
            or state.data.get("confirmed_delivery_at")
            or ""
        ).strip()

        if dry_run or skipped:
            description = format_ascend_dropoff_skipped_action(reference_number=reference)
        elif ok:
            description = format_ascend_dropoff_updated_action(
                reference_number=reference,
                appointment_start=appointment_start,
            )
        else:
            return

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=description,
                    ),
                ),
            )
        )

    def record_turvo_update(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        result = state.data.get("turvo_update_result") or {}
        if not isinstance(result, dict):
            result = {}
        stop_name = str(result.get("stop_name") or state.data.get("customer_name") or "").strip()
        start_time = str(result.get("start_time") or "").strip()
        extraction = state.data.get("customer_reply_extraction") or {}
        if not start_time and isinstance(extraction, dict):
            start_time = str(extraction.get("turvo_start_time") or "").strip()

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_turvo_delivery_updated_action(
                            stop_name=stop_name,
                            start_time=start_time,
                        ),
                    ),
                ),
            )
        )

    def record_confirmation_sent(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        comm_id = str(state.data.get("confirmation_communication_id") or "").strip() or None
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_confirmation_sent_action(),
                        communication_id=comm_id,
                    ),
                ),
            )
        )

    def record_turvo_tendered(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        reference = str(state.data.get("reference_number") or "").strip()
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_turvo_tendered_action(reference_number=reference),
                    ),
                ),
            )
        )

    def record_reply_completed(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = (
            status_type_from_db(row.get("status")) if row else StatusType.PENDING_REVIEW
        )
        from_sub = (
            sub_status_type_from_db(row.get("sub_status"))
            if row
            else StatusSubType.AWAITING_CUSTOMER_REPLY
        )
        if from_status == StatusType.COMPLETED and from_sub in (
            StatusSubType.NONE,
            StatusSubType.APPOINTMENT_SCHEDULED,
        ):
            return

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PENDING_REVIEW,
                        from_sub_status=from_sub or StatusSubType.AWAITING_CUSTOMER_REPLY,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.APPOINTMENT_SCHEDULED,
                    ),
                ),
            )
        )

    def record_reply_rejected(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = (
            status_type_from_db(row.get("status")) if row else StatusType.PENDING_REVIEW
        )
        from_sub = (
            sub_status_type_from_db(row.get("sub_status"))
            if row
            else StatusSubType.AWAITING_CUSTOMER_REPLY
        )
        if from_status == StatusType.COMPLETED and from_sub == StatusSubType.REJECTED:
            return

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PENDING_REVIEW,
                        from_sub_status=from_sub or StatusSubType.AWAITING_CUSTOMER_REPLY,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.REJECTED,
                    ),
                ),
            )
        )


__all__ = ("AppointmentSchedulingActivityService",)
