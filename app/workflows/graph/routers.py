def pod_exists_router(state):
    return "exists" if state.data.get("pod_exists") else "missing"


def convoy_router(state):
    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def pod_reply_router(state):
    return "is_reply" if state.data.get("is_pod_reply_mail") else "ignore"


def event_type_router(state):
    event_type = state.data.get("event_type")
    if event_type == "email_received":
        return "email_received"
    if event_type == "reminder_due":
        return "reminder_due"
    return "route_completed"