"""Node: enqueue Celery ETAs for reminder_due / escalation_due."""

from __future__ import annotations

from app.services.workflow_reminder_service import WorkflowReminderService


def schedule_tender_reminders(state):
    """Enqueue Celery ETAs for reminder_due / escalation_due (idempotent via lifecycle sub_status)."""
    data = dict(state.data)
    data["workflow_run_id"] = str(state.execution_id)
    workflow_reminder_service = WorkflowReminderService()
    workflow_reminder_service.schedule(data, workflow_name="load_tendering")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True
    return state
