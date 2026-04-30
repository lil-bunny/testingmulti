"""POD request path idempotency (table: `workflow_runs`).

State keys:
- pod_request_blocked: initial route_completed path already anchored for tenant/shipment
- _force_mark_pod_request: duplicate route webhook but POD still missing (send + record attempt)
- _pod_email_context: which send_email path fired
"""

from __future__ import annotations

from app.services.reminder_scheduler import schedule_initial_pod_reminders
from app.tools.workflow_runs import (
    record_workflow_run,
    reminder_run_event_type,
    workflow_initial_path_blocked,
)


def _tenant_id(state):
    t = state.data.get("tenant_id")
    return str(t) if t is not None and str(t).strip() != "" else None


def check_pod_request_triggered(state):
    shipment_id = state.data.get("shipment_id")
    tenant_id = _tenant_id(state)
    workflow_instance_id = state.data.get("workflow_instance_id")

    if not shipment_id:
        state.data["pod_request_blocked"] = False
        return state
    if not tenant_id:
        state.data["pod_request_blocked"] = False
        return state

    sid = str(shipment_id) if shipment_id is not None else None
    wi = str(workflow_instance_id) if workflow_instance_id is not None else None

    evt = state.data.get("event_type")
    et = None if evt is None else str(evt)

    state.data["pod_request_blocked"] = workflow_initial_path_blocked(
        tenant_id=tenant_id,
        event_type=et,
        workflow_instance_id=wi,
        shipment_id=sid,
    )
    return state


def branch_after_send_email_pod_request(state):
    shipment_id = state.data.get("shipment_id") or ""
    tenant_id = _tenant_id(state)
    workflow_instance_id = state.data.get("workflow_instance_id") or ""
    sid = str(shipment_id) if shipment_id else None

    route_ctx = state.data.pop("_pod_email_context", None)

    blocked = bool(state.data.get("pod_request_blocked"))
    force_mark = bool(state.data.pop("_force_mark_pod_request", False))

    reminder_eta = (
        state.data.get("event_type") == "reminder_due"
        and state.data.pop("_pod_request_from_reminder", False)
    )

    if reminder_eta and sid and tenant_id:
        rem_et = reminder_run_event_type(state.data.get("reminder_step"))
        scheduled = (
            bool(record_workflow_run(
                tenant_id=tenant_id,
                event_type=rem_et,
                workflow_instance_id=str(workflow_instance_id),
                shipment_id=sid,
            ))
            if rem_et
            else False
        )
        state.data["_schedule_pod_reminders_after_email"] = scheduled
        return state

    if (
        state.data.get("event_type") == "route_completed"
        and route_ctx == "route_completed_primary"
        and tenant_id
    ):
        scheduled = False
        if sid:
            if not blocked:
                scheduled = record_workflow_run(
                    tenant_id=tenant_id,
                    event_type="route_completed",
                    workflow_instance_id=str(workflow_instance_id),
                    shipment_id=sid,
                )
            elif blocked and force_mark:
                scheduled = record_workflow_run(
                    tenant_id=tenant_id,
                    event_type="route_completed",
                    workflow_instance_id=str(workflow_instance_id),
                    shipment_id=sid,
                )
        state.data["_schedule_pod_reminders_after_email"] = scheduled
        return state

    if route_ctx == "process_pod_followup" and sid and tenant_id:
        record_workflow_run(
            tenant_id=tenant_id,
            event_type="process_pod_followup",
            workflow_instance_id=str(workflow_instance_id),
            shipment_id=sid,
        )
        state.data["_schedule_pod_reminders_after_email"] = False
        return state

    state.data["_schedule_pod_reminders_after_email"] = False
    return state


def send_email_continue(state):
    if state.data.pop("_schedule_pod_reminders_after_email", False):
        prev = state.data.get("event_type")
        if state.data.get("event_type") != "route_completed":
            state.data["event_type"] = "route_completed"
        try:
            schedule_initial_pod_reminders(state.data)
        finally:
            state.data["event_type"] = prev
    return state
