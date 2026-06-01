"""Workflow lifecycle nodes — replacements for the old workflow_correlation nodes.

All DB access goes through WorkflowLifecycleService.
"""

from app.core.config import settings
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.turvo import load_id_to_shipment_id


def _turvo_app_user_id(state) -> str | None:
    if state.data.get("app_user_id"):
        return str(state.data["app_user_id"])
    return settings.TURVO_DEFAULT_APP_USER_ID or None


def read_workflow_lifecycle(state):
    """Look up any workflow's lifecycle row with workflow_lifecycles table keys."""
    lifecycle_service = WorkflowLifecycleService()

    workflow_name_key = "lookup_workflow_name" if state.data.get("lookup_workflow_name") else "workflow_name"
    lookup_result = lifecycle_service.read_lifecycle(
        tenant_id=state.data.get("tenant_id"),
        workflow_name=state.data.get(workflow_name_key),
        thread_id=state.data.get("thread_id"),
        shipment_id=state.data.get("shipment_id"),
        load_id=state.data.get("load_id"),
    )

    result_key = "lookup_workflow_lifecycle" if workflow_name_key == "lookup_workflow_name" else "workflow_lifecycle_payload"
    state.data[result_key] = lookup_result

    if lookup_result.get("found"):
        if not state.data.get("thread_id") and lookup_result.get("email_thread_id"):
            state.data["thread_id"] = lookup_result["email_thread_id"]
        if not state.data.get("shipment_id") and lookup_result.get("shipment_id"):
            state.data["shipment_id"] = lookup_result["shipment_id"]
        if not state.data.get("load_id") and lookup_result.get("load_id"):
            state.data["load_id"] = lookup_result["load_id"]
    return state


def check_ratecon_workflow_lifecycle(state):
    """Resolve shipment id if needed and check if a ratecon lifecycle exists."""
    lifecycle_service = WorkflowLifecycleService()

    load_id = state.data.get("load_id")
    shipment_id = state.data.get("shipment_id")

    lid_raw = None
    if load_id is not None:
        ls = str(load_id).strip()
        if ls:
            lid_raw = ls

    sid = None
    if shipment_id is not None:
        ss = str(shipment_id).strip()
        if ss:
            sid = ss

    if not sid:
        if not lid_raw:
            state.data["ratecon_workflow_lifecycle"] = {
                "in_workflow_lifecycle": False,
                "shipment_id": None,
                "load_id": lid_raw,
                "message": "missing_load_id_and_shipment_id",
            }
            return state

        turvo = load_id_to_shipment_id(lid_raw, app_user_id=_turvo_app_user_id(state))
        if turvo.get("success") and turvo.get("shipment_id"):
            sid = str(turvo["shipment_id"]).strip()
            state.data["shipment_id"] = sid
        else:
            state.data["ratecon_workflow_lifecycle"] = {
                "in_workflow_lifecycle": False,
                "shipment_id": None,
                "load_id": lid_raw,
                "message": turvo.get("message", "could_not_resolve_shipment_id"),
            }
            return state

    tenant_id = state.data.get("tenant_id")
    result = lifecycle_service.check_lifecycle_exists(
        tenant_id=tenant_id,
        workflow_name="ratecon",
        shipment_id=sid,
    )

    state.data["ratecon_workflow_lifecycle"] = {
        "in_workflow_lifecycle": result.get("exists", False),
        "lifecycle_id": result.get("lifecycle_id"),
        "shipment_id": sid,
        "load_id": lid_raw,
    }
    return state


def resolve_workflow_lifecycle(state):
    """Resolve or create lifecycle from state correlation keys."""
    lifecycle_service = WorkflowLifecycleService()
    result = lifecycle_service.resolve_or_create_lifecycle(
        tenant_id=state.data.get("tenant_id"),
        workflow_name=state.data.get("workflow_name"),
        payload=state.data,
    )
    state.data["workflow_lifecycle_id"] = result.workflow_lifecycle_id
    state.data["workflow_lifecycle_payload"] = {
        "lifecycle_id": result.workflow_lifecycle_id,
        "existed": result.existed,
    }
    return state
