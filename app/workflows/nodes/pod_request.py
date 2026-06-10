"""POD request scheduling (table: `workflow_runs` records runs at graph start)."""

from __future__ import annotations

from app.domain.pod_lifecycle_settings import hydrate_pod_account_id
from app.services.workflow_reminder_service import WorkflowReminderService


def record_and_schedule_pod_request(state):
    """Post-check node for route_completed: schedule Celery reminders on first successful pass."""
    data = dict(state.data)
    hydrate_pod_account_id(data)
    workflow_reminder_service = WorkflowReminderService()
    workflow_reminder_service.schedule(data, workflow_name="pod_lifecycle")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True

    return state


def record_reminder_run(state):
    """Post-email node for reminder_due events.

    The run row is already recorded by ExecutionService at graph start
    with event_type=reminder_due. No additional recording needed.
    """
    return state
