"""Pure pre-fetch gate evaluation for appointment scheduling ingress."""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.appointment_scheduling.scheduling_reference import is_diamond_scheduling_reference
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.domain.tenant_settings.tms import has_tms_partner_config
from app.tools.turvo_scheduling_ingress import (
    ParsedShipmentUpdateWebhook,
    is_multi_stop_shipment,
    load_id_from_turvo_shipment,
    pickup_changed_in_activity_delta,
    reference_number_from_turvo_shipment,
)


@dataclass(frozen=True)
class FetchedSchedulingIngressData:
    activity_json: dict
    shipment_payload: dict
    reference_number: str
    load_id: str


def evaluate_process_enabled(tenant_settings: dict | None) -> str | None:
    from app.domain.appointment_scheduling.ingress_constants import (
        APPOINTMENT_SCHEDULING_WORKFLOW,
    )

    if APPOINTMENT_SCHEDULING_WORKFLOW not in enabled_processes_from_settings(
        tenant_settings
    ):
        return "process_disabled"
    return None


def evaluate_turvo_configured(tenant_settings: dict | None) -> str | None:
    if not has_tms_partner_config(tenant_settings or {}):
        return "turvo_not_configured"
    return None


def evaluate_parsed_webhook(parsed: ParsedShipmentUpdateWebhook | None) -> str | None:
    if parsed is None:
        return "event_not_shipment_update"
    if not parsed.tender_accepted:
        return "status_not_tender_accepted"
    return None


def evaluate_activity_gates(activity_json: dict) -> str | None:
    if not pickup_changed_in_activity_delta(activity_json):
        return "no_pickup_change"
    return None


def evaluate_shipment_gates(
    shipment_payload: dict,
    *,
    webhook_load_id: str | None,
) -> tuple[str | None, FetchedSchedulingIngressData | None]:
    if is_multi_stop_shipment(shipment_payload):
        return "multi_stop", None

    reference_number = reference_number_from_turvo_shipment(shipment_payload)
    if not reference_number:
        return "missing_reference_number", None
    if not is_diamond_scheduling_reference(reference_number):
        return "non_diamond_customer", None

    load_id = (webhook_load_id or "").strip() or load_id_from_turvo_shipment(shipment_payload) or ""
    if not load_id:
        return "missing_load_id", None

    return None, FetchedSchedulingIngressData(
        activity_json={},
        shipment_payload=shipment_payload,
        reference_number=reference_number,
        load_id=load_id,
    )
