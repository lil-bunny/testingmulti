def end(state):
    # Belt-and-suspenders: clear worker-local POD stage if still present
    # (e.g. early exit before pod_analysis).
    from app.workflows.nodes.pod import _cleanup_pod_attachment_stage

    _cleanup_pod_attachment_stage(state)
    return state


def route_event(state):
    state.data["event_type"] = state.data.get("event_type", "route_completed")
    return state
