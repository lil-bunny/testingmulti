"""Activity log writes for ``appointment_scheduling`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_confirmation_sent_action,
    format_appointment_draft_created_action,
    format_appointment_email_sent_action,
    format_appointment_reply_completed_action,
    format_appointment_scheduling_failed_action,
    format_ascend_dropoff_skipped_action,
    format_ascend_dropoff_updated_action,
    format_scheduling_decision_info,
    format_turvo_delivery_updated_action,
)
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.appointment_scheduling.draft_email import is_costco_customer

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

        customer_name = str(state.data.get("customer_name") or "")
        decision_source = (
            "transit_days" if is_costco_customer(customer_name) else "llm"
        )

        metadata: dict[str, Any] = {
            "reference_number": str(state.data.get("reference_number") or ""),
            "selected_pickup_date": str(decision.get("selected_pickup_date") or ""),
            "calculated_delivery_date": str(decision.get("calculated_delivery_date") or ""),
            "calculated_delivery_weekday": str(
                decision.get("calculated_delivery_weekday") or ""
            ),
            "decision_source": decision_source,
        }
        transit_days = decision.get("transit_days")
        if transit_days is not None:
            metadata["transit_days"] = transit_days

        description = format_scheduling_decision_info(
            reference_number=metadata["reference_number"],
            pickup_date=metadata["selected_pickup_date"],
            delivery_date=metadata["calculated_delivery_date"],
            delivery_weekday=metadata["calculated_delivery_weekday"],
            decision_source=decision_source,
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
                        metadata=metadata,
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
        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        action_metadata: dict[str, Any] = {}
        to_email = str(email_draft.get("to") or "").strip()
        subject = str(email_draft.get("subject") or "").strip()
        reference = str(scheduling_payload.get("reference_number") or "").strip()
        if to_email:
            action_metadata["to"] = to_email
        if subject:
            action_metadata["subject"] = subject
        if reference:
            action_metadata["reference_number"] = reference

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_draft_created_action(),
                        metadata=action_metadata or None,
                    ),
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

    def record_email_sent(
        self,
        state,
        *,
        communication_id: str,
        actor_id: str | None,
    ) -> None:
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
            else StatusSubType.APPOINTMENT_DRAFT_CREATED
        )

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
                        metadata=None,
                        communication_id=communication_id,
                    ),
                ),
            )
        )

    def finalize_confirm_awaiting_reply(
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
        from_status = (
            status_type_from_db(row.get("status")) if row else StatusType.PENDING_REVIEW
        )
        from_sub = (
            sub_status_type_from_db(row.get("sub_status"))
            if row
            else StatusSubType.APPOINTMENT_DRAFT_CREATED
        )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                actor_type=ActorType.USER,
                actor_id=actor_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PENDING_REVIEW,
                        from_sub_status=from_sub or StatusSubType.APPOINTMENT_DRAFT_CREATED,
                        to_status=StatusType.PENDING_REVIEW,
                        to_sub_status=StatusSubType.AWAITING_CUSTOMER_REPLY,
                        metadata={"communication_id": communication_id} if communication_id else None,
                    ),
                ),
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
                    metadata={"ascend_response": result.get("ascend_response")},
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
                    metadata={"turvo_response": result.get("turvo_response")},
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
                        metadata={"updated": result.get("updated"), "ok": result.get("ok")},
                    ),
                ),
            )
        )

    def record_failed(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str | None,
        reason: str,
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
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_scheduling_failed_action(reason=reason),
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PROCESSING,
                        from_sub_status=from_sub or StatusSubType.NONE,
                        to_status=StatusType.FAILED,
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
            metadata: dict[str, Any] = {"dry_run": True, "payload": result.get("payload")}
        elif ok:
            description = format_ascend_dropoff_updated_action(
                reference_number=reference,
                appointment_start=appointment_start,
            )
            metadata = {"payload": result.get("payload"), "response": result.get("response")}
        else:
            description = f"Ascend dropoff update failed for {reference or 'unknown'}"
            metadata = {"error": result.get("error"), "payload": result.get("payload")}

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=description,
                        metadata=metadata or None,
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
                        metadata={"ok": result.get("ok"), "error": result.get("error")},
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

        confirmed_at = str(state.data.get("confirmed_delivery_at") or "").strip() or None
        metadata = {"confirmed_delivery_at": confirmed_at} if confirmed_at else None

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_appointment_reply_completed_action(),
                        metadata=metadata,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PENDING_REVIEW,
                        from_sub_status=from_sub or StatusSubType.AWAITING_CUSTOMER_REPLY,
                        to_status=StatusType.COMPLETED,
                        to_sub_status=StatusSubType.APPOINTMENT_SCHEDULED,
                        metadata=metadata,
                    ),
                ),
            )
        )


__all__ = ("AppointmentSchedulingActivityService",)
