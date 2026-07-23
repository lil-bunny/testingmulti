"""Intake-phase activity logs for appointment scheduling."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_draft_created_action,
    format_appointment_draft_teams_notification_action,
    format_scheduling_decision_info,
)
from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.appointment_scheduling.activity_common import (
    SchedulingActivityDeps,
    lifecycle_already_started,
    scope_ids,
)

logger = get_logger(__name__)


class IntakeActivity:
    def __init__(self, deps: SchedulingActivityDeps) -> None:
        self._deps = deps

    def record_started(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            logger.warning(
                "record_appointment_started skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(getattr(state, "data", {}).get("workflow_lifecycle_id")),
                bool(getattr(state, "tenant_id", None) or getattr(state, "data", {}).get("tenant_id")),
                bool(getattr(state, "execution_id", None)),
            )
            return

        wl_id, tenant_id, run_id = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
        if lifecycle_already_started(row):
            logger.info(
                "record_appointment_started skipping already started lifecycle_id=%s",
                wl_id,
            )
            return

        self._deps.apply(
            LifecycleTransitionCommand(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=StatusType.NONE,
                from_sub_status=StatusSubType.NONE,
                to_status=StatusType.PROCESSING,
                to_sub_status=StatusSubType.APPOINTMENT_SCHEDULING_STARTED,
            )
        )

    def record_decision(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        data = getattr(state, "data", None) or {}
        decision = data.get("llm_appointment_decision") or {}
        if not isinstance(decision, dict):
            decision = {}

        description = format_scheduling_decision_info(
            reference_number=str(data.get("reference_number") or ""),
            pickup_date=str(decision.get("selected_pickup_date") or ""),
            delivery_date=str(decision.get("calculated_delivery_date") or ""),
            delivery_weekday=str(decision.get("calculated_delivery_weekday") or ""),
            decision_source="llm",
        )

        self._deps.apply(self._deps.action_from_state(state, description=description))

    def record_draft_ready(
        self,
        state,
        *,
        email_draft: dict[str, Any],
        appointment_payload: dict[str, Any],
    ) -> None:
        if scope_ids(state) is None:
            return
        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_appointment_draft_created_action(),
            )
        )

    def record_draft_pending_review(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        self._deps.apply(
            LifecycleTransitionCommand(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=from_status or StatusType.PROCESSING,
                from_sub_status=from_sub or StatusSubType.APPOINTMENT_SCHEDULING_STARTED,
                to_status=StatusType.PENDING_REVIEW,
                to_sub_status=StatusSubType.APPOINTMENT_DRAFT_CREATED,
            )
        )

    def record_draft_teams_notification(self, state) -> None:
        if scope_ids(state) is None:
            return
        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_appointment_draft_teams_notification_action(),
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
                "record_appointment_failed skipped missing ids "
                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
                bool(wl_id),
                bool(tenant),
                bool(run_id),
            )
            return

        metadata = {
            "error": failure.code,
            "error_category": failure.category.value,
            "error_description": failure.message,
        }
        self._deps.activity_log.record_exception(
            ActivityLogWrite(
                tenant_id=tenant,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                description=failure.message,
                metadata=metadata,
                actor_type=ActorType.SYSTEM,
            )
        )

        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        self._deps.apply(
            LifecycleTransitionCommand(
                tenant_id=tenant,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=from_status or StatusType.PROCESSING,
                from_sub_status=from_sub or StatusSubType.NONE,
                to_status=StatusType.PENDING_REVIEW,
                to_sub_status=StatusSubType.NONE,
            )
        )
