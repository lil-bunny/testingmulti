from __future__ import annotations

from app.domain.gelita.routing_guide_lifecycle import gelita_current_routing_guide_attempt
from app.domain.load_tendering_settings import is_ftl_load_type, resolve_load_type
from app.domain.load_tendering_state import get_tender
from app.services.workflow_reminder_service import WorkflowReminderService


def schedule_tender_reminders(state):
    """Enqueue Celery ETAs for reminder_due / escalation_due (idempotent via lifecycle sub_status)."""
    data = dict(state.data)
    data["workflow_run_id"] = str(state.execution_id)
    if is_ftl_load_type(resolve_load_type(state)):
        data["routing_guide_attempt"] = gelita_current_routing_guide_attempt(
            get_tender(state.data)
        )
    workflow_reminder_service = WorkflowReminderService()
    workflow_reminder_service.schedule(data, workflow_name="load_tendering")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True
    return state
