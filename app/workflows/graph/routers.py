def pod_exists_router(state):
    return "exists" if state.data.get("pod_exists") else "missing"


def convoy_router(state):
    return "convoy" if state.data.get("is_convoy") else "non_convoy"


def get_shipment_router(state):
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
        return "is_found" if state.data.get("workflow_correlation_found") else "missing"
    
    return "check_existing_pod"

def event_type_router(state):
    event_type = state.data.get("event_type")
    if event_type == "email_received":
        return "email_received"
    if event_type == "reminder_due":
        return "reminder_due"
    return "route_completed"