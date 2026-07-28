"""Rebuild in-run graph state from slim lifecycle metadata + shipment row."""

from __future__ import annotations

from typing import Any

from datetime import datetime, timezone

from app.domain.appointment_scheduling.constants import APPOINTMENT_PAYLOAD, EMAIL_DRAFT
from app.domain.appointment_scheduling.utils import iso_or_empty
from app.tools.appointment_scheduling.dates import (
    is_weekend_shifted_truthy,
    utc_to_local_date_and_time,
)


def _coerce_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def apply_lifecycle_email_draft_to_state(
    state,
    lifecycle_metadata: dict[str, Any],
) -> None:
    if isinstance(lifecycle_metadata.get(EMAIL_DRAFT), dict):
        state.data[EMAIL_DRAFT] = lifecycle_metadata[EMAIL_DRAFT]


def rebuild_llm_appointment_decision_from_shipment_row(
    shipment_row: dict[str, Any] | None,
) -> dict[str, Any]:
    """Rebuild ephemeral send-path decision view from durable shipment facts."""
    if not shipment_row:
        return {}

    meta = shipment_row.get("metadata") or {}
    if not isinstance(meta, dict):
        meta = {}

    weekend_shifted = is_weekend_shifted_truthy(meta.get("weekend_shifted"))
    proposed_pickup = _coerce_utc_datetime(shipment_row.get("proposed_pickup"))
    proposed_delivery = _coerce_utc_datetime(shipment_row.get("proposed_delivery"))
    pickup_tz = str(shipment_row.get("pickup_timezone") or "").strip() or None
    delivery_tz = str(shipment_row.get("delivery_timezone") or "").strip() or None

    if not proposed_pickup and not proposed_delivery and not weekend_shifted:
        return {}

    decision: dict[str, Any] = {"weekend_shifted": weekend_shifted}

    if proposed_pickup:
        pickup_date, pickup_time = utc_to_local_date_and_time(
            proposed_pickup,
            timezone_name=pickup_tz,
        )
        if pickup_date:
            decision["selected_pickup_date"] = pickup_date
        if pickup_time:
            decision["selected_pickup_time"] = pickup_time

    if proposed_delivery:
        delivery_date, _ = utc_to_local_date_and_time(
            proposed_delivery,
            timezone_name=delivery_tz,
        )
        if delivery_date:
            try:
                local_delivery = datetime.strptime(delivery_date, "%Y-%m-%d")
            except ValueError:
                local_delivery = None
            if local_delivery is not None:
                decision["calculated_delivery_date"] = local_delivery.strftime("%m/%d/%Y")
                decision["calculated_delivery_weekday"] = local_delivery.strftime("%A").upper()

    return decision


def rebuild_appointment_payload_from_shipment(
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
    existing = state_data.get(APPOINTMENT_PAYLOAD)
    if isinstance(existing, dict):
        for key in ("proposed_pickup_at", "proposed_delivery_at", "shipment_details"):
            val = str(existing.get(key) or "").strip()
            if val:
                payload[key] = val
    if shipment_row:
        pickup = iso_or_empty(shipment_row.get("proposed_pickup"))
        delivery = iso_or_empty(shipment_row.get("proposed_delivery"))
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
    pickup_date = iso_or_empty(shipment_row.get("pickup_date"))
    delivery_date = iso_or_empty(shipment_row.get("delivery_date"))
    if pickup_date:
        state.data["pickup_date"] = pickup_date
    if delivery_date:
        state.data["delivery_date"] = delivery_date
    state.data[APPOINTMENT_PAYLOAD] = rebuild_appointment_payload_from_shipment(
        shipment_row=shipment_row,
        state_data=state.data,
    )
