from __future__ import annotations

from typing import Any

from app.domain.state import tenant_slug_from_payload, workflow_state_data
from app.integrations.turvo.shipments import (
    delivery_address_from_global_route_stop,
    global_route_stops_from_payload,
)
from app.services.shipment_location_link_service import ShipmentLocationLinkService
from app.services.shipments_service import ShipmentsService
from app.tools.turvo import check_pod_by_shipment_id as check_pod_tool
from app.tools.turvo import get_shipment as get_shipment_tool
from app.tools.turvo import load_id_to_shipment_id as load_id_to_shipment_id_tool
from app.tools.turvo import update_shipment as update_shipment_tool
from app.tools.turvo import upload_to_turvo as upload_to_turvo_tool
from app.workflows.shipment_resolver import resolve_shipment_id, resolve_shipment_id_for_fetch


def turvo_call_kwargs(state: Any) -> dict[str, str | None]:
    """Kwargs for ``app.tools.turvo`` from LangGraph ``state`` or payload dict."""
    return {"tenant_slug": tenant_slug_from_payload(workflow_state_data(state))}


def _merge_pod_exists_from_turvo(state) -> None:
    """Set ``pod_exists`` from webhook hint plus Turvo documents when the check succeeds."""
    webhook_pod = bool(state.data.get("existing_pod"))
    shipment_id = state.data.get("shipment_id")
    if not shipment_id:
        state.data["pod_exists"] = webhook_pod
        return
    result = check_pod_tool(shipment_id, **turvo_call_kwargs(state))
    state.data["turvo_pod_check"] = result
    if result.get("success"):
        state.data["pod_exists"] = webhook_pod or bool(result.get("pod_exists"))
    else:
        state.data["pod_exists"] = webhook_pod


def get_shipment(state):
    sid_state = resolve_shipment_id(state.data)
    shipment = get_shipment_tool(
        sid_state,
        **turvo_call_kwargs(state),
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


def resolve_load_to_shipment(state):
    """Resolve ``load_id`` to Turvo ``shipment_id``; stores tool result under ``load_id_to_shipment``."""
    load_id = state.data.get("load_id")
    result = load_id_to_shipment_id_tool(
        load_id,
        **turvo_call_kwargs(state),
    )
    state.data["load_id_to_shipment"] = result
    if result.get("success") and result.get("shipment_id"):
        state.data["shipment_id"] = result["shipment_id"]
        load_id_str = str(load_id).strip() if load_id is not None else ""
        if load_id_str:
            persist = ShipmentsService().upsert_from_turvo(
                tenant_id=state.data.get("tenant_id"),
                turvo_shipment_id=str(result["shipment_id"]),
                load_id=load_id_str,
            )
            state.data["shipment_persist"] = persist
            if persist.get("success") and persist.get("shipments_row_id"):
                state.data["shipments_row_id"] = persist["shipments_row_id"]
        else:
            state.data["shipment_persist"] = {
                "success": False,
                "message": "missing_load_id",
            }
    return state


def link_shipment_locations(state):
    """Resolve route endpoints to ``locations`` ids and update ``shipments`` FKs."""
    shipment = state.data.get("shipment") or {}
    stops = global_route_stops_from_payload(
        shipment if isinstance(shipment, dict) else {}
    )
    details = shipment.get("details") if isinstance(shipment.get("details"), dict) else None
    result = ShipmentLocationLinkService().link_from_route_stops(
        stops,
        shipments_row_id=state.data.get("shipments_row_id"),
        delivery_address_builder=delivery_address_from_global_route_stop,
        shipment_details=details,
    )
    state.data["shipment_location_link"] = {
        "success": True,
        "pickup_location_id": result.pickup_location_id,
        "delivery_location_id": result.delivery_location_id,
        "delivery_address": result.delivery_address,
        "pickup": {
            "city": result.pickup.city,
            "state_code": result.pickup.state_code,
            "country": result.pickup.country,
        },
        "delivery": {
            "city": result.delivery.city,
            "state_code": result.delivery.state_code,
            "country": result.delivery.country,
        },
    }
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
