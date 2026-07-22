"""Rebuild in-run graph state from slim lifecycle metadata + shipment row."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.domain.appointment_scheduling.metadata_keys import EMAIL_DRAFT


def apply_lifecycle_email_draft_to_state(
    state,
    lifecycle_metadata: dict[str, Any],
) -> None:
    if isinstance(lifecycle_metadata.get(EMAIL_DRAFT), dict):
        state.data["email_draft"] = lifecycle_metadata[EMAIL_DRAFT]
        state.data.setdefault("workflow_lifecycle_metadata", lifecycle_metadata)


def _iso_or_empty(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value).strip()


def rebuild_scheduling_payload_from_shipment(
    *,
    shipment_row: dict[str, Any] | None,
    state_data: dict[str, Any],
) -> dict[str, Any]:
    meta = (shipment_row or {}).get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    reference = str(
        state_data.get("reference_number")
        or meta.get("reference_number")
        or ""
    ).strip()
    payload: dict[str, Any] = {}
    if reference:
        payload["reference_number"] = reference
    existing = state_data.get("scheduling_payload")
    if isinstance(existing, dict):
        for key in ("proposed_pickup_at", "proposed_delivery_at", "shipment_details"):
            val = str(existing.get(key) or "").strip()
            if val:
                payload[key] = val
    if shipment_row:
        pickup = _iso_or_empty(shipment_row.get("proposed_pickup"))
        delivery = _iso_or_empty(shipment_row.get("proposed_delivery"))
        if pickup and "proposed_pickup_at" not in payload:
            payload["proposed_pickup_at"] = pickup
        if delivery and "proposed_delivery_at" not in payload:
            payload["proposed_delivery_at"] = delivery
    return payload


def hydrate_shipment_facts_into_state(
    state,
    *,
    shipment_row: dict[str, Any],
) -> None:
    meta = shipment_row.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}
    reference = str(meta.get("reference_number") or state.data.get("reference_number") or "").strip()
    if reference:
        state.data["reference_number"] = reference
    load_id = str(meta.get("load_id") or state.data.get("load_id") or "").strip()
    if load_id:
        state.data["load_id"] = load_id
    customer_name = str(shipment_row.get("customer_name") or state.data.get("customer_name") or "").strip()
    if customer_name:
        state.data["customer_name"] = customer_name
    pickup_date = _iso_or_empty(shipment_row.get("pickup_date"))
    delivery_date = _iso_or_empty(shipment_row.get("delivery_date"))
    if pickup_date:
        state.data["pickup_date"] = pickup_date
    if delivery_date:
        state.data["delivery_date"] = delivery_date
    state.data["scheduling_payload"] = rebuild_scheduling_payload_from_shipment(
        shipment_row=shipment_row,
        state_data=state.data,
    )
