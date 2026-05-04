def pod_exists_router(state):
    return "exists" if state.data.get("pod_exists") else "missing"


def pod_missing_dispatch_router(state):
    """
    POD missing:
    - route_completed (not process_pod follow-up): schedule Celery steps 0–2 only.
    - reminder_due: send email in this run (after Turvo check), i.e. queued reminder fired.
    - anything else (e.g. follow-up refresh): no send; only scheduled reminders may mail.
    """
    if state.data.get("pod_exists"):
        return "exists"
    if (
        state.data.get("event_type") == "route_completed"
        and state.data.get("_pod_email_context") != "process_pod_followup"
    ):
        return "schedule_initial"
    if state.data.get("event_type") == "reminder_due":
        return "send_now"
    return "skip_send"


def convoy_router(state):
    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def shipment_router(state):
    event_type = event_type_router(state)

    if event_type == "email_received":
        shipment = state.data.get("shipment") or {}
        status_key = (
            shipment.get("data", {})
            .get("status", {})
            .get("code", {})
            .get("key")
        )
        allowed_status_codes = {"2116", "2106", "2105"} # Route Complete, EnRoute, At Delivery
        return "valid_shipment_status" if str(status_key) in allowed_status_codes else "invalid_shipment_status"

    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def pod_reply_router(state):
    return "is_reply" if state.data.get("is_pod_attached") else "missing"

def read_workflow_correlation_router(state):
    event_type = event_type_router(state)
    if event_type == "email_received":
        return "is_found" if state.data.get("workflow_correlation").get("found") else "missing"
    
    return "check_existing_pod"

def event_type_router(state):
    event_type = state.data.get("event_type")
    if event_type == "email_received":
        return "email_received"
    if event_type == "reminder_due":
        return "reminder_due"
    return "route_completed"


def pod_request_triggered_router(state):
    return "blocked" if state.data.get("pod_request_blocked") else "continue"


def pod_request_mark_router(state):
    return "marked" if state.data.get("_schedule_pod_reminders_after_email") else "skipped_mark"


def noop_always_router(state):
    """Single-key router for fan-in when two nodes must lead to one target."""
    return "go"


def noop_followup_route(state):
    return "followup" if state.data.get("_pod_request_from_followup") else "main"

