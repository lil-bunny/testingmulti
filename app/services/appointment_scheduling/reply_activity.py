"""Reply-phase activity logs for appointment scheduling."""

from __future__ import annotations

from app.domain.appointment_scheduling.activity_log_descriptions import (
    format_appointment_confirmation_sent_action,
    format_ascend_dropoff_skipped_action,
    format_ascend_dropoff_updated_action,
    format_turvo_delivery_updated_action,
    format_turvo_tendered_action,
)
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.appointment_scheduling.activity_common import (
    SchedulingActivityDeps,
    scope_ids,
)


class ReplyActivity:
    def __init__(self, deps: SchedulingActivityDeps) -> None:
        self._deps = deps

    def record_ascend_update(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        data = getattr(state, "data", None) or {}
        result = data.get("ascend_update_result") or {}
        if not isinstance(result, dict):
            result = {}
        reference = str(data.get("reference_number") or "").strip()
        dry_run = bool(result.get("dry_run"))
        skipped = bool(result.get("skipped"))
        ok = bool(result.get("ok"))
        extraction = data.get("customer_reply_extraction") or {}
        appointment_start = str(
            (extraction.get("appointment_start_iso") if isinstance(extraction, dict) else None)
            or data.get("confirmed_delivery_at")
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

        self._deps.apply(self._deps.action_from_state(state, description=description))

    def record_turvo_update(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        data = getattr(state, "data", None) or {}
        result = data.get("turvo_update_result") or {}
        if not isinstance(result, dict):
            result = {}
        stop_name = str(result.get("stop_name") or data.get("customer_name") or "").strip()
        start_time = str(result.get("start_time") or "").strip()
        extraction = data.get("customer_reply_extraction") or {}
        if not start_time and isinstance(extraction, dict):
            start_time = str(extraction.get("turvo_start_time") or "").strip()

        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_turvo_delivery_updated_action(
                    stop_name=stop_name,
                    start_time=start_time,
                ),
            )
        )

    def record_confirmation_sent(self, state) -> None:
        if scope_ids(state) is None:
            return
        data = getattr(state, "data", None) or {}
        comm_id = str(data.get("confirmation_communication_id") or "").strip() or None
        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_appointment_confirmation_sent_action(),
                communication_id=comm_id,
            )
        )

    def record_turvo_tendered(self, state) -> None:
        if scope_ids(state) is None:
            return
        data = getattr(state, "data", None) or {}
        reference = str(data.get("reference_number") or "").strip()
        self._deps.apply(
            self._deps.action_from_state(
                state,
                description=format_turvo_tendered_action(reference_number=reference),
            )
        )

    def record_reply_completed(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
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

        self._deps.apply(
            LifecycleTransitionCommand(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=from_status or StatusType.PENDING_REVIEW,
                from_sub_status=from_sub or StatusSubType.AWAITING_CUSTOMER_REPLY,
                to_status=StatusType.COMPLETED,
                to_sub_status=StatusSubType.APPOINTMENT_SCHEDULED,
            )
        )

    def record_reply_rejected(self, state) -> None:
        scope = scope_ids(state)
        if scope is None:
            return

        wl_id, tenant_id, run_id = scope
        row = self._deps.lifecycle.read_lifecycle_row_by_id(wl_id)
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

        self._deps.apply(
            LifecycleTransitionCommand(
                tenant_id=tenant_id,
                workflow_lifecycle_id=wl_id,
                workflow_run_id=run_id,
                activity_type=ActivityType.STATUS_CHANGE,
                from_status=from_status or StatusType.PENDING_REVIEW,
                from_sub_status=from_sub or StatusSubType.AWAITING_CUSTOMER_REPLY,
                to_status=StatusType.COMPLETED,
                to_sub_status=StatusSubType.REJECTED,
            )
        )
