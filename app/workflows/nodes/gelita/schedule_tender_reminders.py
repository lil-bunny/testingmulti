"""Node: enqueue Celery ETAs for reminder_due / escalation_due."""

from __future__ import annotations

from app.services.gelita_reminder_scheduler import schedule_tender_reminders as enqueue_gelita_tender_reminders


def schedule_tender_reminders(state):
    """Enqueue Celery ETAs for reminder_due / escalation_due (idempotent via lifecycle sub_status)."""
    data = dict(state.data)
    data["workflow_run_id"] = str(state.execution_id)
    enqueue_gelita_tender_reminders(data)
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True
    return state
