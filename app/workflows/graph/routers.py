def pod_exists_router(state):
    return "exists" if state.data.get("pod_exists") else "missing"


def pod_missing_dispatch_router(state):
    """
    POD missing:
    - route_completed: schedule Celery steps 0–2 only (no synchronous email).
    - reminder_due: send email in this run (after Turvo check), i.e. queued reminder fired.
    - anything else: no send; only scheduled reminders may mail.
    """
    if state.data.get("pod_exists"):
        return "exists"
    if state.data.get("event_type") == "route_completed":
        return "schedule_initial"
    if state.data.get("event_type") == "reminder_due":
        return "send_now"
    return "skip_send"


def shipment_router(state):
    event_type = event_type_router(state)

    if event_type == "email_received":
        shipment = state.data.get("shipment") or {}
        status_key = (
            shipment.get("details", {})
            .get("status", {})
            .get("code", {})
            .get("key")
        )
        allowed_status_codes = {"2116", "2106", "2105"} # Route Complete, EnRoute, At Delivery
        return "valid_shipment_status" if str(status_key) in allowed_status_codes else "invalid_shipment_status"

    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def read_workflow_lifecycle_router(state):
    event_type = event_type_router(state)
    if event_type == "email_received":
        lifecycle = (
            state.data.get("lookup_workflow_lifecycle")
            or state.data.get("workflow_lifecycle_payload")
            or state.data.get("ratecon_workflow_lifecycle")
            or {}
        )
        return "is_found" if lifecycle.get("found") else "missing"
    return "missing"


def event_type_router(state):
    event_type = state.data.get("event_type")
    if event_type == "email_received":
        return "email_received"
    if event_type == "reminder_due":
        return "reminder_due"
    return "route_completed"


def pod_request_triggered_router(state):
    return "blocked" if state.data.get("pod_request_blocked") else "continue"
