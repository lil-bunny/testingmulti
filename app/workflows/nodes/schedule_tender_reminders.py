from __future__ import annotations

from app.core.logger import get_logger
from app.domain.gelita.routing_guide_lifecycle import (
    routing_guide_attempt_from_state,
    routing_guide_reminders_scheduled_for_attempt,
)
from app.domain.load_tendering_settings import is_ftl_load_type, resolve_load_type
from app.services.routing_guide_lifecycle_service import RoutingGuideLifecycleService
from app.services.workflow_reminder_service import WorkflowReminderService

logger = get_logger(__name__)


def schedule_tender_reminders(state):
    """Enqueue Celery ETAs for reminder_due / escalation_due (idempotent via lifecycle sub_status)."""
    data = dict(state.data)
    data["workflow_run_id"] = str(state.execution_id)
    attempt: int | None = None
    if is_ftl_load_type(resolve_load_type(state)):
        attempt = routing_guide_attempt_from_state(state.data)
        data["routing_guide_attempt"] = attempt
        wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        lifecycle_meta = state.data.get("workflow_lifecycle_metadata")
        if isinstance(lifecycle_meta, dict) and routing_guide_reminders_scheduled_for_attempt(
            lifecycle_meta,
            attempt,
        ):
            logger.info(
                "schedule_tender_reminders skipped: already scheduled for attempt=%s lifecycle_id=%s",
                attempt,
                wl_id,
            )
            return state

    workflow_reminder_service = WorkflowReminderService()
    workflow_reminder_service.schedule(data, workflow_name="load_tendering")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True
        if attempt is not None:
            routing_guide_lifecycle_service = RoutingGuideLifecycleService()
            routing_guide_lifecycle_service.mark_reminders_scheduled_for_attempt(
                state,
                attempt=attempt,
            )
    return state
