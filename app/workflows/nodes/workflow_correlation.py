from app.core.config import settings
from app.tools.workflow_correlation import (
    map_thread_to_workflow,
    persist_correlation_thread_for_shipment,
    ratecon_shipment_in_workflow_correlation,
    read_by_key,
    upsert_by_key,
)
from app.workflows.shipment_resolver import resolve_shipment_id


def _resolve_correlation_key(state) -> str:
    return (
        state.data.get("thread_id")
        or state.data.get("load_id")
        or state.data.get("shipment_id")
        or "default"
    )


def _turvo_app_user_id(state) -> str | None:
    if state.data.get("app_user_id"):
        return str(state.data["app_user_id"])
    return settings.TURVO_DEFAULT_APP_USER_ID or None


def check_ratecon_workflow_correlation(state):
    """Resolve shipment id if needed and set ``ratecon_workflow_correlation`` on state."""
    result = ratecon_shipment_in_workflow_correlation(
        state.data.get("load_id"),
        shipment_id=state.data.get("shipment_id"),
        app_user_id=_turvo_app_user_id(state),
    )
    state.data["ratecon_workflow_correlation"] = result
    return state


def add_thread_for_shipment(state):
    """Persist Unipile thread + load on workflow_correlation (insert when no row for this shipment)."""
    rc = state.data.get("ratecon_workflow_correlation") or {}
    if rc.get("in_workflow_correlation"):
        state.data["ratecon_correlation_thread_persist"] = {
            "skipped": True,
            "reason": "already_in_workflow_correlation",
        }
        return state

    thread_id = state.data.get("thread_id")
    if thread_id is None or not str(thread_id).strip():
        state.data["ratecon_correlation_thread_persist"] = {
            "skipped": True,
            "reason": "missing_thread_id",
        }
        return state

    shipment_id = state.data.get("shipment_id") or rc.get("shipment_id")
    load_id = state.data.get("load_id")
    wid = state.data.get("workflow_instance_id")
    wname = state.data.get("workflow_name")
    out = persist_correlation_thread_for_shipment(
        str(shipment_id) if shipment_id is not None else "",
        str(load_id) if load_id is not None else "",
        str(thread_id).strip(),
        workflow_instance_id=str(wid).strip() if wid is not None else None,
        workflow_name=str(wname).strip() if wname is not None else None,
    )
    state.data["ratecon_correlation_thread_persist"] = out
    return state


def read_workflow_correlation(state):
    result = read_by_key(_resolve_correlation_key(state))
    state.data["workflow_correlation"] = result
    return state


def update_workflow_correlation(state):
    payload = state.data.get("workflow_correlation_payload", {}).copy()
    payload.setdefault("workflow_name", state.data.get("workflow_name", "pod_lifecycle"))
    payload.setdefault("workflow_instance_id", state.data.get("workflow_instance_id", ""))
    payload.setdefault("shipment_id", resolve_shipment_id(state.data))
    payload.setdefault("load_id", state.data.get("load_id"))
    payload.setdefault("email_thread_id", state.data.get("thread_id"))
    result = upsert_by_key(_resolve_correlation_key(state), payload)
    map_thread_to_workflow(
        state.data.get("thread_id", ""),
        state.data.get("workflow_instance_id", ""),
    )
    state.data["workflow_correlation"] = result
    return state
