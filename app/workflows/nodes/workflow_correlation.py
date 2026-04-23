from app.tools.workflow_correlation import map_thread_to_workflow, read_by_key, upsert_by_key


def _resolve_correlation_key(state) -> str:
    return (
        state.data.get("thread_id")
        or state.data.get("load_id")
        or state.data.get("shipment_id")
        or "default"
    )


def read_workflow_correlation(state):
    result = read_by_key(_resolve_correlation_key(state))
    state.data["workflow_correlation"] = result
    return state


def update_workflow_correlation(state):
    payload = state.data.get("workflow_correlation_payload", {}).copy()
    payload.setdefault("workflow_name", state.data.get("workflow_name", "pod_lifecycle"))
    payload.setdefault("workflow_instance_id", state.data.get("workflow_instance_id", ""))
    payload.setdefault("shipment_id", state.data.get("shipment_id"))
    payload.setdefault("load_id", state.data.get("load_id"))
    payload.setdefault("email_thread_id", state.data.get("thread_id"))
    result = upsert_by_key(_resolve_correlation_key(state), payload)
    map_thread_to_workflow(
        state.data.get("thread_id", ""),
        state.data.get("workflow_instance_id", ""),
    )
    state.data["workflow_correlation"] = result
    return state
