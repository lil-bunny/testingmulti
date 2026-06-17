"""Activity log writes for ``driver_assignment`` workflow."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import (
    format_driver_assignment_not_started_action,
    format_driver_assignment_started_action,
    format_driver_reminders_scheduled_action,
)
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db
from app.models.activity_type import ActivityType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


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
        return meta

    @staticmethod
    def _lifecycle_already_started(row: dict[str, Any] | None) -> bool:
        if not row:
            return False
        status = status_type_from_db(row.get("status"))
        return status not in (None, StatusType.NONE)

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
                        to_sub_status=StatusSubType.NONE,
                        from_status=StatusType.NONE,
                        from_sub_status=StatusSubType.NONE,
                        metadata=meta,
                    ),
                ),
            )
        )


__all__ = ("DriverAssignmentActivityService",)
