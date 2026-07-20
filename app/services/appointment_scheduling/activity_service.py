"""Activity log writes for ``appointment_scheduling`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_draft_created_action,
    format_appointment_email_sent_action,
    format_appointment_scheduling_failed_action,
    format_scheduling_decision_info,
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
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        from_status=from_status or StatusType.PENDING_REVIEW,
                        from_sub_status=from_sub or StatusSubType.APPOINTMENT_DRAFT_CREATED,
                        to_status=StatusType.PENDING_REVIEW,
                        to_sub_status=StatusSubType.AWAITING_CUSTOMER_REPLY,
                        metadata=None,
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


__all__ = ("AppointmentSchedulingActivityService",)
