"""Workflow lifecycle nodes — replacements for the old workflow_correlation nodes.

All DB access goes through WorkflowLifecycleService.
"""

from app.domain.state import workflow_state_data
from app.services.workflow_lifecycle_service import WorkflowLifecycleService


def read_workflow_lifecycle(state):
    """Look up any workflow's lifecycle row with workflow_lifecycles table keys."""
    lifecycle_service = WorkflowLifecycleService()
    data = workflow_state_data(state)

    workflow_name_key = (
        "lookup_workflow_name" if data.get("lookup_workflow_name") else "workflow_name"
    )
    data.get(workflow_name_key)
    db_shipment_id = lifecycle_service._extract_db_shipment_id(data)
    shipment_fk = db_shipment_id or lifecycle_service.resolve_shipments_row_id(
        tenant_id=data.get("tenant_id"),
        payload=data,
    )

    lookup_result = lifecycle_service.read_lifecycle(
        tenant_id=state.data.get("tenant_id"),
        workflow_name=state.data.get(workflow_name_key),
        thread_id=state.data.get("thread_id"),
        shipment_id=shipment_fk,
        tender_id=state.data.get("tender_id"),
    )

    result_key = (
        "lookup_workflow_lifecycle"
        if workflow_name_key == "lookup_workflow_name"
        else "workflow_lifecycle_payload"
    )
    state.data[result_key] = lookup_result

    if lookup_result.get("found"):
        wn = str(state.data.get(workflow_name_key) or "").strip()
        if (
            not state.data.get("thread_id")
            and lookup_result.get("email_thread_id")
            and wn not in ("ratecon", "pod_lifecycle")
        ):
            state.data["thread_id"] = lookup_result["email_thread_id"]
        if not state.data.get("shipment_id") and lookup_result.get("shipment_id"):
            state.data["shipment_id"] = lookup_result["shipment_id"]
        if not state.data.get("tender_id") and lookup_result.get("tender_id"):
            state.data["tender_id"] = lookup_result["tender_id"]
    return state


def check_ratecon_workflow_lifecycle(state):
    """Verify ratecon lifecycle exists by ``shipments.id`` FK or email thread."""
    lifecycle_service = WorkflowLifecycleService()
    data = workflow_state_data(state)
    tenant_id = data.get("tenant_id")

    shipments_row_id = lifecycle_service.resolve_shipments_row_id(
        tenant_id=tenant_id,
        payload=data,
    )
    if not shipments_row_id:
        state.data["ratecon_workflow_lifecycle"] = {
            "in_workflow_lifecycle": False,
            "shipments_row_id": None,
            "lifecycle_id": None,
            "shipment_id": data.get("shipment_id"),
            "load_id": data.get("load_id"),
            "message": "missing_shipments_row_id",
        }
        return state

    result = lifecycle_service.check_lifecycle_exists(
        tenant_id=tenant_id,
        workflow_name="ratecon",
        shipment_id=shipments_row_id,
    )

    state.data["ratecon_workflow_lifecycle"] = {
        "in_workflow_lifecycle": result.get("exists", False),
        "lifecycle_id": result.get("lifecycle_id"),
        "shipments_row_id": shipments_row_id,
        "shipment_id": data.get("shipment_id"),
        "load_id": data.get("load_id"),
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
    lifecycle_service.ensure_lifecycle_shipment_linked(
        lifecycle_id=result.workflow_lifecycle_id,
        tenant_id=state.data.get("tenant_id"),
        payload=state.data,
    )
    state.data["workflow_lifecycle_id"] = result.workflow_lifecycle_id
    state.data["workflow_lifecycle_payload"] = {
        "lifecycle_id": result.workflow_lifecycle_id,
        "existed": result.existed,
    }
    return state
