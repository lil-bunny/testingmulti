from app.tools.turvo import get_shipment as get_shipment_tool
from app.tools.turvo import update_shipment as update_shipment_tool


def get_shipment(state):
    shipment = get_shipment_tool(state.data.get("shipment_id"))

    state.data["shipment"] = shipment
    state.data["is_convoy"] = shipment.get("convoy", False) #TO-DO check if carrier is convoy

    return state


def update_shipment(state):
    update_shipment_tool(state.data)

    return state


def check_existing_pod(state):
    state.data["pod_exists"] = bool(state.data.get("existing_pod"))
    return state