"""POD request scheduling (table: `workflow_runs` records runs at graph start)."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.pod_lifecycle_settings import hydrate_pod_account_id
from app.services.pod_lifecycle.reminder_eligibility_service import (
    PodLifecycleReminderEligibilityService,
)
from app.services.workflow_reminder_service import WorkflowReminderService

logger = get_logger(__name__)


def record_and_schedule_pod_request(state):
    """Post-check node for route_completed: schedule Celery reminders on first successful pass."""
    data = dict(state.data)
    hydrate_pod_account_id(data)
    workflow_reminder_service = WorkflowReminderService()
    workflow_reminder_service.schedule(data, workflow_name="pod_lifecycle")
    if data.get("reminders_scheduled"):
        state.data["reminders_scheduled"] = True

    return state


def check_pod_reminder_eligibility(state):
    """Layer-3 gate before ``send_email`` on ``reminder_due`` (lifecycle sub_status skip list)."""
    wl_id = state.data.get("workflow_lifecycle_id")
    result = PodLifecycleReminderEligibilityService().check(
        workflow_lifecycle_id=wl_id,
        state_data=state.data,
    )
    if result.skip_reason:
        state.data["pod_reminder_eligible"] = False
        state.data["pod_reminder_skip_reason"] = result.skip_reason
        logger.info(
            "check_pod_reminder_eligibility skip lifecycle_id=%s reason=%s",
            wl_id,
            result.skip_reason,
        )
    else:
        state.data["pod_reminder_eligible"] = True
    return state


def record_reminder_run(state):
    """Post-email node for reminder_due events.

    The run row is already recorded by ExecutionService at graph start
    with event_type=reminder_due. No additional recording needed.
    """
    return state
