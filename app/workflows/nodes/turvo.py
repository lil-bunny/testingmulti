from app.tools.turvo import get_shipment as get_shipment_tool
from app.tools.turvo import update_shipment as update_shipment_tool
from app.tools.turvo import upload_to_turvo as upload_to_turvo_tool
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipment_id_for_fetch


def get_shipment(state):
    shipment_id = resolve_shipment_id_for_fetch(state.data)
    shipment = get_shipment_tool(shipment_id)

    state.data["shipment"] = shipment
    canonical = resolve_shipment_id(state.data)
    if canonical:
        state.data["shipment_id"] = canonical
    state.data["is_convoy"] = shipment.get("convoy", False) #TO-DO check if carrier is convoy

    return state


def upload_to_turvo(state):
    upload_to_turvo_tool(state.data)
    return state


def update_shipment(state):
    update_shipment_tool(state.data)

    return state


def check_existing_pod(state):
    state.data["pod_exists"] = bool(state.data.get("existing_pod"))
    return state