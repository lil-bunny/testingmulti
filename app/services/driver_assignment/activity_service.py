"""Activity log writes for ``driver_assignment`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.driver_assignment.activity_log_descriptions import (
    format_driver_ambiguous_in_tms_action,
    format_driver_assigned_in_tms_action,
    format_driver_assign_to_tms_failed_action,
    format_driver_confirmation_tracking_sent_action,
    format_driver_confirmation_default_sent_action,
    format_driver_already_assigned_in_tms_action,
    format_driver_assignment_not_started_action,
    format_driver_details_partial_follow_up_action,
    format_driver_escalation_sent_action,
    format_driver_not_found_in_tms_action,
    format_driver_reminder_sent_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.tms_connection_activity_service import TmsConnectionActivityService
from app.services.driver_assignment.shipment_driver_details_service import (
    DriverAssignmentShipmentDetailsService,
)
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService
from app.domain.driver_assignment.guards import driver_assignment_reminder_skip_sub_statuses
from app.domain.driver_assignment.reminder_ladder import schedule_reminder_step_from_payload
from app.tools.driver_details import normalize_phone_digits
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

logger = get_logger(__name__)

_DRIVER_ASSIGNMENT_WORKFLOW = "driver_assignment"


class DriverAssignmentActivityService:
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
    def _communication_id(state) -> str | None:
        """Email comm id from graph state (inbound reply or outbound send), not TMS lookups."""
        raw = state.data.get("communication_id")
        if raw is None:
            return None
        cid = str(raw).strip()
        return cid or None

    @staticmethod
    def _tms_assign_metadata(state) -> dict[str, Any] | None:
        """Event-specific metadata for a successful TMS driver assign action only."""
        meta: dict[str, Any] = {}
        extraction = state.data.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        if isinstance(driver, dict):
            name = driver.get("name")
            phone = driver.get("phone")
            if name:
                meta["driver_name"] = name
            if phone:
                meta["driver_phone"] = phone
        contact_id = state.data.get("tms_contact_id")
        if contact_id is not None and str(contact_id).strip() != "":
            meta["tms_contact_id"] = contact_id
        if state.data.get("tms_contact_created"):
            meta["tms_contact_created"] = True
        return meta or None

    @staticmethod
    def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
        if not row:
            return False
        status = status_type_from_db(row.get("status"))
        return status not in (None, StatusType.NONE)

    @staticmethod
    def _skip_sub_statuses_from_state(state) -> frozenset[str]:
        return driver_assignment_reminder_skip_sub_statuses()

    @staticmethod
    def _sub_status_for_reminder_step(step: int) -> StatusSubType | None:
        mapping = {
            1: StatusSubType.REMINDER_1_SENT,
            2: StatusSubType.REMINDER_2_SENT,
            3: StatusSubType.REMINDER_3_SENT,
            4: StatusSubType.REMINDER_4_SENT,
        }
        return mapping.get(step)

    @staticmethod
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
            )
        return ActivityLogStep(
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=to_status,
            to_sub_status=new_sub,
        )

    @staticmethod
    def _build_success_sub_status_step(
        *,
        current_status: StatusType | None,
        new_sub: StatusSubType,
    ) -> ActivityLogStep:
        preserve_status = current_status if current_status is not None else StatusType.PROCESSING
        return ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_status=preserve_status,
            to_sub_status=new_sub,
        )

    def record_not_started_on_ratecon(
        self,
        *,
        tenant_id: str,
        ratecon_workflow_lifecycle_id: str,
        workflow_run_id: str,
        skip_reason: str,
        shipment_id: str | None = None,
        load_id: str | None = None,
        shipments_row_id: str | None = None,
        pickup_appointment_at: str | None = None,
        pickup_appointment_timezone: str | None = None,
    ) -> None:
        _ = (
            shipment_id,
            load_id,
            shipments_row_id,
            pickup_appointment_at,
            pickup_appointment_timezone,
        )
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=ratecon_workflow_lifecycle_id,
                workflow_run_id=workflow_run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_assignment_not_started_action(
                            reason=skip_reason
                        ),
                    ),
                ),
            )
        )

    def record_reminder_sent(self, state) -> None:
        if not state.data.get("driver_reminder_sent"):
            logger.info(
                "record_reminder_sent skipping (reminder not sent) lifecycle_id=%s",
                state.data.get("workflow_lifecycle_id"),
            )
            return

        scope = self._scope_ids(state)
        if scope is None:
            logger.warning(
                "record_reminder_sent skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        raw_step = state.data.get("reminder_step")
        try:
            step = int(raw_step) if raw_step is not None else None
        except (TypeError, ValueError):
            step = None
        if step not in (1, 2, 3, 4):
            logger.warning(
                "record_reminder_sent invalid reminder_step=%r lifecycle_id=%s",
                raw_step,
                wl_id,
            )
            return

        new_sub = self._sub_status_for_reminder_step(step)
        assert new_sub is not None

        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        skip = delayed_workflow_step_skip_reason(
            prev,
            skip_sub_statuses=self._skip_sub_statuses_from_state(state),
        )
        if skip:
            logger.info(
                "record_reminder_sent skipping lifecycle_id=%s reason=%s",
                wl_id,
                skip,
            )
            return

        action_description = (
            format_driver_details_partial_follow_up_action()
            if state.data.get("driver_reminder_is_partial_follow_up")
            else format_driver_reminder_sent_action(step=step)
        )

        if (
            state.data.get("driver_reminder_is_partial_follow_up")
            and state.data.get("driver_reminder_skip_sub_status_bump")
        ):
            self._activity.record_sequence(
                ActivityLogSequence(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    steps=(
                        ActivityLogStep(
                            activity_type=ActivityType.ACTION,
                            description=action_description,
                            communication_id=self._communication_id(state),
                        ),
                    ),
                )
            )
            return

        current_status = status_type_from_db(prev.get("status")) if prev else None
        transition_step = self._build_reminder_transition_step(
            current_status=current_status,
            new_sub=new_sub,
        )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=action_description,
                        communication_id=self._communication_id(state),
                    ),
                    transition_step,
                ),
            )
        )

        if not state.data.get("driver_reminder_is_partial_follow_up"):
            schedule_step = schedule_reminder_step_from_payload(state.data)
            if schedule_step is not None:
                self._lifecycle.append_driver_assignment_sent_schedule_step(
                    lifecycle_id=wl_id,
                    schedule_step=schedule_step,
                )

    def record_started(self, state) -> None:
        if not state.data.get("reminders_scheduled"):
            logger.info(
                "record_driver_assignment_started skipping (reminders not scheduled) "
                "lifecycle_id=%s",
                state.data.get("workflow_lifecycle_id"),
            )
            return

        scope = self._scope_ids(state)
        if scope is None:
            logger.warning(
                "record_driver_assignment_started skipped missing ids "
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
                "record_driver_assignment_started skipping already started lifecycle_id=%s",
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
                        to_status=StatusType.PROCESSING,
                        to_sub_status=StatusSubType.DRIVER_ASSIGNMENT_STARTED,
                        from_status=StatusType.NONE,
                        from_sub_status=StatusSubType.NONE,
                    ),
                ),
            )
        )

    @staticmethod
    def _tms_match_value(state) -> tuple[str, str]:
        match_by = str(state.data.get("tms_search_match_by") or "name").strip()
        extraction = state.data.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        if not isinstance(driver, dict):
            driver = {}
        if match_by in ("phone", "name_and_phone"):
            digits = normalize_phone_digits(driver.get("phone"))
            val = f"***{digits[-4:]}" if len(digits) >= 4 else "****"
            return match_by, val
        if match_by == "email":
            return match_by, str(driver.get("email") or "?").strip() or "?"
        return match_by, str(driver.get("name") or "?").strip() or "?"

    def record_tms_driver_not_resolved(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        resolution = str(state.data.get("tms_resolution") or "").strip()
        match_by, match_value = self._tms_match_value(state)
        steps: list[ActivityLogStep] = []
        if resolution == "not_found":
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.INFO,
                    description=format_driver_not_found_in_tms_action(),
                )
            )
        elif resolution == "ambiguous":
            count = int(state.data.get("tms_match_count") or 0)
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_driver_ambiguous_in_tms_action(
                        match_by=match_by,
                        match_value=match_value,
                        count=count,
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

    def record_tms_driver_error(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        if state.data.get("tms_connection_timed_out"):
            TmsConnectionActivityService(activity_log_service=self._activity).record_timeout(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                communication_id=self._communication_id(state),
            )
            return
        reason = str(state.data.get("tms_driver_error") or "unknown").strip() or "unknown"
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_assign_to_tms_failed_action(reason=reason),
                    ),
                ),
            )
        )

    @staticmethod
    def _driver_assignment_completed_step(
        *,
        from_status: StatusType | None,
        from_sub_status: StatusSubType | None,
    ) -> ActivityLogStep | None:
        if from_status == StatusType.COMPLETED and from_sub_status == StatusSubType.UPLOADED_TO_TMS:
            return None
        if from_status != StatusType.COMPLETED:
            return ActivityLogStep(
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=from_status,
                to_status=StatusType.COMPLETED,
                from_sub_status=from_sub_status,
                to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            )
        if from_sub_status != StatusSubType.UPLOADED_TO_TMS:
            return ActivityLogStep(
                activity_type=ActivityType.SUB_STATUS_CHANGE,
                from_sub_status=from_sub_status,
                to_sub_status=StatusSubType.UPLOADED_TO_TMS,
            )
        return None

    def record_tms_driver_success(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        resolution = str(state.data.get("tms_resolution") or "").strip()
        if resolution == "skipped_already_assigned":
            data = state.data
            if not str(data.get("tms_matched_driver_name") or "").strip() and not str(
                data.get("tms_matched_driver_phone") or ""
            ).strip():
                DriverAssignmentShipmentDetailsService().persist_from_turvo_shipment(state)
        WorkflowReminderCancelService().cancel_all(lifecycle_id=wl_id)
        assign_meta = self._tms_assign_metadata(state)

        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        current_status = status_type_from_db(prev.get("status")) if prev else None
        current_sub = sub_status_type_from_db(prev.get("sub_status")) if prev else None

        steps: list[ActivityLogStep] = []

        if resolution == "skipped_already_assigned":
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.INFO,
                    description=format_driver_already_assigned_in_tms_action(),
                )
            )
            if current_sub != StatusSubType.UPLOADED_TO_TMS:
                steps.append(
                    self._build_success_sub_status_step(
                        current_status=current_status,
                        new_sub=StatusSubType.UPLOADED_TO_TMS,
                    )
                )
            completed = self._driver_assignment_completed_step(
                from_status=current_status,
                from_sub_status=StatusSubType.UPLOADED_TO_TMS,
            )
            if completed is not None:
                steps.append(completed)
        else:
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_driver_assigned_in_tms_action(),
                    metadata=assign_meta,
                )
            )
            if current_sub != StatusSubType.UPLOADED_TO_TMS:
                steps.append(
                    self._build_success_sub_status_step(
                        current_status=current_status,
                        new_sub=StatusSubType.UPLOADED_TO_TMS,
                    )
                )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=tuple(steps),
            )
        )
        state.data["driver_details_recorded"] = True

    def complete_when_driver_already_in_tms(self, state) -> None:
        """Complete DA when Turvo already has a driver (reminder/escalation path)."""
        if self._scope_ids(state) is None:
            return
        if not str(state.data.get("tms_resolution") or "").strip():
            state.data["tms_resolution"] = "skipped_already_assigned"
        self.record_tms_driver_success(state)

    def record_driver_details_confirmation_sent(self, state) -> None:
        if not state.data.get("driver_confirmation_sent"):
            return
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        is_tracking = bool(state.data.get("tms_is_tracking_customer"))
        description = (
            format_driver_confirmation_tracking_sent_action()
            if is_tracking
            else format_driver_confirmation_default_sent_action()
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
                        communication_id=self._communication_id(state),
                    ),
                ),
            )
        )

    def record_driver_assignment_completed(self, state) -> None:
        if not state.data.get("driver_confirmation_sent"):
            return
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(prev.get("status")) if prev else None
        from_sub = sub_status_type_from_db(prev.get("sub_status")) if prev else None
        completed = self._driver_assignment_completed_step(
            from_status=from_status,
            from_sub_status=from_sub,
        )
        if completed is None:
            return
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(completed,),
            )
        )

    def record_escalation_sent(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            logger.warning(
                "record_escalation_sent skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        skip = delayed_workflow_step_skip_reason(
            prev,
            skip_sub_statuses=self._skip_sub_statuses_from_state(state),
        )
        if skip:
            logger.info(
                "record_escalation_sent skipping lifecycle_id=%s reason=%s",
                wl_id,
                skip,
            )
            return
        if sub_status_type_from_db((prev or {}).get("sub_status")) == StatusSubType.ESCALATED:
            logger.info(
                "record_escalation_sent skipping already escalated lifecycle_id=%s",
                wl_id,
            )
            return

        current_status = status_type_from_db(prev.get("status")) if prev else None
        transition_step = self._build_reminder_transition_step(
            current_status=current_status,
            new_sub=StatusSubType.ESCALATED,
        )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_escalation_sent_action(),
                    ),
                    transition_step,
                ),
            )
        )


__all__ = ("DriverAssignmentActivityService",)
