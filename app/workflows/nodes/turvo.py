from app.core.config import settings
from app.tools.turvo import check_pod_by_shipment_id as check_pod_tool
from app.tools.turvo import get_shipment as get_shipment_tool
from app.tools.turvo import update_shipment as update_shipment_tool
from app.tools.turvo import upload_to_turvo as upload_to_turvo_tool
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipment_id_for_fetch


def _turvo_app_user_id(state) -> str | None:
    """Prefer run state; fall back to env default (same choice as previous tool behavior)."""
    if state.data.get("app_user_id"):
        return str(state.data["app_user_id"])
    return settings.TURVO_DEFAULT_APP_USER_ID or None


def _merge_pod_exists_from_turvo(state) -> None:
    """Set ``pod_exists`` from webhook hint plus Turvo documents when the check succeeds."""
    webhook_pod = bool(state.data.get("existing_pod"))
    shipment_id = state.data.get("shipment_id")
    if not shipment_id:
        state.data["pod_exists"] = webhook_pod
        return
    result = check_pod_tool(shipment_id, app_user_id=_turvo_app_user_id(state))
    state.data["turvo_pod_check"] = result
    if result.get("success"):
        state.data["pod_exists"] = webhook_pod or bool(result.get("pod_exists"))
    else:
        state.data["pod_exists"] = webhook_pod


def get_shipment(state):
    sid_state = resolve_shipment_id(state.data)
    shipment = get_shipment_tool(
        sid_state,
        app_user_id=_turvo_app_user_id(state),
    )

    state.data["shipment"] = shipment
    details = shipment.get("details") or {}
    carrier_order = details.get("carrierOrder") or []
    carrier_name = ""
    if carrier_order and isinstance(carrier_order[0], dict):
        carrier = carrier_order[0].get("carrier") or {}
        carrier_name = str(carrier.get("name") or "")

    state.data["is_convoy"] = (
        "convoy" in carrier_name.lower()
        if carrier_name
        else bool(shipment.get("convoy", False))
    )

    return state


def upload_to_turvo(state):
    upload_to_turvo_tool(state.data)
    return state


def update_shipment(state):
    update_shipment_tool(state.data)

    return state


def check_existing_pod(state):
    _merge_pod_exists_from_turvo(state)
    if (
        state.data.get("event_type") == "route_completed"
        and state.data.get("pod_request_blocked")
        and not state.data.get("pod_exists")
    ):
        state.data["_force_mark_pod_request"] = True
    return state


def refresh_pod_before_send_email(state):
    """Re-query Turvo for POD before ``send_email`` (e.g. after process_pod follow-up)."""
    _merge_pod_exists_from_turvo(state)
    return state
