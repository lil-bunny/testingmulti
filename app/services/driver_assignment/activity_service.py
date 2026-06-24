"""Activity log writes for ``driver_assignment`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_details_received_from_email_action,
    format_driver_ambiguous_in_tms_action,
    format_driver_assigned_in_tms_action,
    format_driver_assign_to_tms_failed_action,
    format_driver_confirmation_tracking_sent_action,
    format_driver_confirmation_default_sent_action,
    format_driver_already_assigned_in_tms_action,
    format_driver_assignment_not_started_action,
    format_driver_assignment_started_action,
    format_driver_created_in_tms_action,
    format_driver_details_partial_follow_up_action,
    format_driver_escalation_sent_action,
    format_driver_found_in_tms_action,
    format_driver_not_found_in_tms_action,
    format_driver_reminder_sent_action,
    format_driver_reminders_scheduled_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType
from app.domain.tenant_settings.workflow_shadow_mode import shadow_metadata_patch
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_reminder_service import parse_reminders_for_workflow
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
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _scope_ids(state) -> tuple[str, str, str] | None:
        wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
        run_id = str(state.execution_id or "").strip()
        if not wl_id or not tenant_id or not run_id:
            return None
        return wl_id, tenant_id, run_id

    @staticmethod
    def _base_metadata(state) -> dict[str, Any]:
        meta: dict[str, Any] = {}
        for key in (
            "shipment_id",
            "shipments_row_id",
            "thread_id",
            "load_id",
            "ratecon_workflow_lifecycle_id",
            "pickup_appointment_at",
            "pickup_appointment_timezone",
            "pickup_appointment_source",
        ):
            raw = state.data.get(key)
            if raw is not None and str(raw).strip():
                meta[key] = str(raw).strip()
        wl_id = state.data.get("workflow_lifecycle_id")
        if wl_id is not None and str(wl_id).strip():
            meta["workflow_lifecycle_id"] = str(wl_id).strip()
        meta.update(shadow_metadata_patch(state.data))
        return meta

    @staticmethod
    def _communication_id(state) -> str | None:
        raw = state.data.get("communication_id")
        if raw is None:
            return None
        cid = str(raw).strip()
        return cid or None

    @staticmethod
    def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
        if not row:
            return False
        status = status_type_from_db(row.get("status"))
        return status not in (None, StatusType.NONE)

    @staticmethod
    def _skip_sub_statuses_from_state(state) -> frozenset[str]:
        data = getattr(state, "data", None) or {}
        if not isinstance(data, dict):
            return frozenset()
        cfg = parse_reminders_for_workflow(data, _DRIVER_ASSIGNMENT_WORKFLOW)
        if cfg is None:
            return frozenset()
        return frozenset(s.strip() for s in cfg.skip_sub_statuses if str(s).strip())

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
        meta: dict[str, Any] = {"skip_reason": skip_reason}
        for key, val in (
            ("shipment_id", shipment_id),
            ("load_id", load_id),
            ("shipments_row_id", shipments_row_id),
            ("pickup_appointment_at", pickup_appointment_at),
            ("pickup_appointment_timezone", pickup_appointment_timezone),
        ):
            cleaned = self._clean(val)
            if cleaned:
                meta[key] = cleaned

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
                        metadata=meta,
                    ),
                ),
            )
        )

    def record_reminders_scheduled(self, state) -> None:
        if not state.data.get("reminders_scheduled"):
            return

        scope = self._scope_ids(state)
        if scope is None:
            logger.warning(
                "record_reminders_scheduled skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(state.data.get("workflow_lifecycle_id")),
                bool(state.tenant_id or state.data.get("tenant_id")),
                bool(state.execution_id),
            )
            return

        wl_id, tenant_id, run_id = scope
        meta = self._base_metadata(state)
        schedule = state.data.get("driver_reminder_schedule")
        if isinstance(schedule, dict):
            for key in (
                "pickup_appointment_at",
                "pickup_appointment_timezone",
                "reminder_steps",
                "skipped_steps",
            ):
                if key in schedule:
                    meta[key] = schedule[key]

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_reminders_scheduled_action(),
                        metadata=meta,
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

        meta = self._base_metadata(state)
        meta["reminder_step"] = step
        if state.data.get("driver_reminder_is_partial_follow_up"):
            meta["partial_follow_up"] = True

        action_description = (
            format_driver_details_partial_follow_up_action(step=step)
            if state.data.get("driver_reminder_is_partial_follow_up")
            else format_driver_reminder_sent_action(step=step)
        )

        if (
            state.data.get("driver_reminder_is_partial_follow_up")
            and state.data.get("driver_reminder_skip_sub_status_bump")
        ):
            meta["ladder_at_cap"] = True
            self._activity.record_sequence(
                ActivityLogSequence(
                    tenant_id=tenant_id,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    steps=(
                        ActivityLogStep(
                            activity_type=ActivityType.ACTION,
                            description=action_description,
                            metadata=dict(meta),
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
            metadata=meta,
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
                        metadata=dict(meta),
                        communication_id=self._communication_id(state),
                    ),
                    transition_step,
                ),
            )
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

        meta = self._base_metadata(state)
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_assignment_started_action(),
                        metadata=meta,
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=StatusType.PROCESSING,
                        to_sub_status=StatusSubType.DRIVER_ASSIGNMENT_STARTED,
                        from_status=StatusType.NONE,
                        from_sub_status=StatusSubType.NONE,
                        metadata=meta,
                    ),
                ),
            )
        )

    @staticmethod
    def _tms_metadata(state) -> dict[str, Any]:
        meta = DriverAssignmentActivityService._base_metadata(state)
        extraction = state.data.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        if isinstance(driver, dict):
            for key in ("name", "phone", "email"):
                val = driver.get(key)
                if val:
                    meta[f"driver_{key}"] = val
        for key in (
            "tms_driver_outcome",
            "tms_resolution",
            "tms_contact_id",
            "tms_match_count",
            "tms_search_match_by",
            "tms_follow_up_reason",
            "tms_carrier_id",
            "tms_shipment_id",
            "tms_created_contact",
        ):
            raw = state.data.get(key)
            if raw is not None and str(raw).strip() != "":
                meta[key] = raw
        err = state.data.get("tms_driver_error")
        if err:
            meta["tms_driver_error"] = str(err)
        if state.data.get("tms_is_tracking_customer"):
            meta["tms_is_tracking_customer"] = True
        customer = state.data.get("tms_customer_name")
        if customer:
            meta["tms_customer_name"] = str(customer)
        return meta

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

    @staticmethod
    def _driver_from_state(state) -> dict[str, Any]:
        extraction = state.data.get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        return driver if isinstance(driver, dict) else {}

    def record_tms_driver_not_resolved(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        resolution = str(state.data.get("tms_resolution") or "").strip()
        meta = self._tms_metadata(state)
        match_by, match_value = self._tms_match_value(state)
        steps: list[ActivityLogStep] = []
        if resolution == "not_found":
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_driver_not_found_in_tms_action(
                        match_by=match_by,
                        match_value=match_value,
                    ),
                    metadata=dict(meta),
                    communication_id=self._communication_id(state),
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
                    metadata=dict(meta),
                    communication_id=self._communication_id(state),
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
        reason = str(state.data.get("tms_driver_error") or "unknown").strip() or "unknown"
        meta = self._tms_metadata(state)
        meta["tms_resolution"] = "failed"
        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_assign_to_tms_failed_action(reason=reason),
                        metadata=meta,
                        communication_id=self._communication_id(state),
                    ),
                ),
            )
        )

    @staticmethod
    def _driver_assignment_completed_step(
        *,
        from_status: StatusType | None,
        from_sub_status: StatusSubType | None,
        metadata: dict[str, Any],
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
                metadata=dict(metadata),
            )
        if from_sub_status != StatusSubType.UPLOADED_TO_TMS:
            return ActivityLogStep(
                activity_type=ActivityType.SUB_STATUS_CHANGE,
                from_sub_status=from_sub_status,
                to_sub_status=StatusSubType.UPLOADED_TO_TMS,
                metadata=dict(metadata),
            )
        return None

    @staticmethod
    def _confirmation_metadata(state) -> dict[str, Any]:
        meta = DriverAssignmentActivityService._tms_metadata(state)
        if state.data.get("tms_is_tracking_customer"):
            meta["tms_is_tracking_customer"] = True
            meta["confirmation_email_variant"] = "tracking"
        else:
            meta["confirmation_email_variant"] = "default"
        customer = state.data.get("tms_customer_name")
        if customer:
            meta["tms_customer_name"] = customer
        return meta

    def record_tms_driver_success(self, state) -> None:
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        driver = self._driver_from_state(state)
        meta = self._tms_metadata(state)
        resolution = str(state.data.get("tms_resolution") or "").strip()
        match_by, match_value = self._tms_match_value(state)
        contact_id = state.data.get("tms_contact_id")

        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        current_status = status_type_from_db(prev.get("status")) if prev else None
        current_sub = sub_status_type_from_db(prev.get("sub_status")) if prev else None

        steps: list[ActivityLogStep] = []

        if resolution == "skipped_already_assigned":
            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_driver_already_assigned_in_tms_action(),
                    metadata=dict(meta),
                    communication_id=self._communication_id(state),
                )
            )
            if current_sub != StatusSubType.UPLOADED_TO_TMS:
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.UPLOADED_TO_TMS,
                        metadata=dict(meta),
                    )
                )
            completed = self._driver_assignment_completed_step(
                from_status=current_status,
                from_sub_status=StatusSubType.UPLOADED_TO_TMS,
                metadata=meta,
            )
            if completed is not None:
                steps.append(completed)
        else:
            if resolution == "created":
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_not_found_in_tms_action(
                            match_by=match_by,
                            match_value=match_value,
                        ),
                        metadata=dict(meta),
                        communication_id=self._communication_id(state),
                    )
                )
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_created_in_tms_action(
                            name=str(driver.get("name") or "?"),
                            contact_id=contact_id or "?",
                        ),
                        metadata=dict(meta),
                    )
                )
            elif resolution == "found" and contact_id is not None:
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_driver_found_in_tms_action(
                            match_by=match_by,
                            match_value=match_value,
                            contact_id=contact_id,
                        ),
                        metadata=dict(meta),
                        communication_id=self._communication_id(state),
                    )
                )

            if current_sub != StatusSubType.DETAILS_RECEIVED:
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=format_details_received_from_email_action(
                            name=driver.get("name"),
                            phone=driver.get("phone"),
                            email=driver.get("email"),
                        ),
                        metadata=dict(meta),
                        communication_id=self._communication_id(state),
                    )
                )
                steps.append(
                    self._build_reminder_transition_step(
                        current_status=current_status,
                        new_sub=StatusSubType.DETAILS_RECEIVED,
                        metadata=meta,
                    )
                )

            steps.append(
                ActivityLogStep(
                    activity_type=ActivityType.ACTION,
                    description=format_driver_assigned_in_tms_action(),
                    metadata=dict(meta),
                )
            )
            if current_sub != StatusSubType.UPLOADED_TO_TMS:
                steps.append(
                    ActivityLogStep(
                        activity_type=ActivityType.SUB_STATUS_CHANGE,
                        to_sub_status=StatusSubType.UPLOADED_TO_TMS,
                        metadata=dict(meta),
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

    def record_driver_details_confirmation_sent(self, state) -> None:
        if not state.data.get("driver_confirmation_sent"):
            return
        scope = self._scope_ids(state)
        if scope is None:
            return
        wl_id, tenant_id, run_id = scope
        meta = self._confirmation_metadata(state)
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
                        metadata=dict(meta),
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
        meta = self._confirmation_metadata(state)
        prev = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(prev.get("status")) if prev else None
        from_sub = sub_status_type_from_db(prev.get("sub_status")) if prev else None
        completed = self._driver_assignment_completed_step(
            from_status=from_status,
            from_sub_status=from_sub,
            metadata=meta,
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

        meta = self._base_metadata(state)
        enrich = state.data.get("shipment_display_enrich")
        if isinstance(enrich, dict):
            for key in ("carrier_name", "customer_name", "delivery_date"):
                val = enrich.get(key)
                if val is not None and str(val).strip():
                    meta[key] = str(val).strip()

        current_status = status_type_from_db(prev.get("status")) if prev else None
        from_sub = sub_status_type_from_db(prev.get("sub_status")) if prev else None
        transition_step = ActivityLogStep(
            activity_type=ActivityType.SUB_STATUS_CHANGE,
            to_sub_status=StatusSubType.ESCALATED,
            from_sub_status=from_sub,
            from_status=current_status,
            to_status=current_status,
            metadata=dict(meta),
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
                        metadata=dict(meta),
                    ),
                    transition_step,
                ),
            )
        )


__all__ = ("DriverAssignmentActivityService",)
