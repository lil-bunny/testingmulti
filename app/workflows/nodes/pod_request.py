"""POD request path idempotency (table: `workflow_runs`).

State keys:
- pod_request_blocked: initial route_completed path already anchored for tenant/shipment
- _force_mark_pod_request: duplicate route webhook but POD still missing (send + record attempt)
"""

from __future__ import annotations

from app.services.reminder_scheduler import schedule_pod_reminders
from app.services.workflow_runs_service import WorkflowRunsService


def _tenant_id(state):
    t = state.data.get("tenant_id")
    return str(t) if t is not None and str(t).strip() != "" else None


def check_pod_request_triggered(state):
    """Dedup gate: has this shipment already had its initial route_completed recorded in workflow_runs?"""
    runs_service = WorkflowRunsService()
    shipment_id = state.data.get("shipment_id")
    tenant_id = _tenant_id(state)

    if not shipment_id or not tenant_id:
        state.data["pod_request_blocked"] = False
        return state
    state.data["pod_request_blocked"] = runs_service.is_workflow_initial_path_blocked(
        tenant_id=tenant_id,
        event_type=state.data.get("event_type"),
        workflow_lifecycle_id=state.data.get("workflow_lifecycle_id"),
        shipment_id=shipment_id,
        exclude_run_id=state.execution_id,
    )
    return state


def record_and_schedule_pod_request(state):
    """Post-check node for route_completed: schedule Celery reminders if this is the first successful pass.

    The run row itself is already recorded by ExecutionService at graph start.
    This node only decides whether to enqueue reminder tasks.
    """
    blocked = bool(state.data.get("pod_request_blocked"))
    force_mark = bool(state.data.pop("_force_mark_pod_request", False))

    if not blocked or force_mark:
        schedule_pod_reminders(state.data)

    return state


def record_reminder_run(state):
    """Post-email node for reminder_due events.

    The run row is already recorded by ExecutionService at graph start
    with event_type=reminder_due. No additional recording needed.
    """
    return state
