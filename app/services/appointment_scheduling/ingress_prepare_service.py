"""Worker-side prepare for appointment scheduling Turvo pickup ingress.

Owns Turvo shipment/activity fetch, diamond/multi-stop/pickup gates, sheet recipient
resolution, shipment upsert, and lifecycle create. HTTP webhook only enqueues a slim
payload (tenant + shipment_id + optional load_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.asyncio_util import run_sync
from app.core.logger import get_logger
from app.domain.appointment_scheduling.constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.domain.appointment_scheduling.models import CustomerContactRow
from app.integrations.turvo.activity import fetch_shipment_activity_list
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    appointment_scheduling_display_fields_from_payload,
    delivery_stop_name_from_payload,
    get_shipment,
)
from app.services.appointment_scheduling.ingress_service import (
    evaluate_activity_gates,
    evaluate_shipment_gates,
)
from app.services.appointment_scheduling.intake_service import resolve_recipient_contact
from app.services.shipment_location_link_service import ShipmentLocationLinkService
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngressPrepareResult:
    ok: bool
    skip_reason: str | None = None
    workflow_lifecycle_id: str | None = None
    shipments_row_id: str | None = None
    reference_number: str | None = None
    load_id: str | None = None
    shipment: dict[str, Any] | None = None
    customer_contact: CustomerContactRow | None = None
    customer_name: str | None = None


class IngressPrepareService:
    def __init__(
        self,
        *,
        shipments_service: ShipmentsService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
        location_link_service: ShipmentLocationLinkService | None = None,
    ) -> None:
        self._shipments = shipments_service or ShipmentsService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._location_link = location_link_service or ShipmentLocationLinkService()

    def prepare_pickup_changed(
        self,
        *,
        tenant_slug: str,
        tenant_id: str,
        tenant_settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> IngressPrepareResult:
        existing_lifecycle_id = str(payload.get("workflow_lifecycle_id") or "").strip()
        existing_shipments_row_id = str(payload.get("shipments_row_id") or "").strip()
        shipment_payload = payload.get("shipment")
        if not isinstance(shipment_payload, dict):
            shipment_payload = None

        if existing_lifecycle_id and existing_shipments_row_id:
            customer_name = str(payload.get("customer_name") or "").strip() or None
            if not customer_name and isinstance(shipment_payload, dict):
                customer_name = delivery_stop_name_from_payload(shipment_payload) or None
            raw_contact = payload.get("customer_contact")
            contact: CustomerContactRow | None = None
            if isinstance(raw_contact, CustomerContactRow):
                contact = raw_contact
            elif isinstance(raw_contact, dict) and str(raw_contact.get("email") or "").strip():
                contact = CustomerContactRow.model_validate(raw_contact)
            reference_number = str(payload.get("reference_number") or "").strip() or None
            load_id = str(payload.get("load_id") or "").strip() or None
            return IngressPrepareResult(
                ok=True,
                workflow_lifecycle_id=existing_lifecycle_id,
                shipments_row_id=existing_shipments_row_id,
                reference_number=reference_number,
                load_id=load_id,
                shipment=None,
                customer_contact=contact,
                customer_name=customer_name,
            )

        shipment_id = str(payload.get("shipment_id") or "").strip()
        tenant_uuid = str(tenant_id or "").strip()
        if not shipment_id or not tenant_uuid:
            return IngressPrepareResult(ok=False, skip_reason="lifecycle_create_failed")

        if shipment_payload is None:
            try:
                shipment_payload = run_sync(get_shipment(tenant_slug, shipment_id))
            except (TurvoApiError, ValueError) as exc:
                logger.warning(
                    "appointment_scheduling prepare shipment fetch failed "
                    "tenant_slug=%s shipment_id=%s error=%s",
                    tenant_slug,
                    shipment_id,
                    exc,
                )
                return IngressPrepareResult(
                    ok=False,
                    skip_reason="turvo_shipment_fetch_failed",
                )

        if not isinstance(shipment_payload, dict):
            return IngressPrepareResult(ok=False, skip_reason="turvo_shipment_fetch_failed")

        webhook_load_id = str(payload.get("load_id") or "").strip() or None
        reason, fetched = evaluate_shipment_gates(
            shipment_payload,
            webhook_load_id=webhook_load_id,
        )
        if reason or fetched is None:
            return IngressPrepareResult(
                ok=False,
                skip_reason=reason or "missing_reference_number",
            )

        try:
            activity_json = run_sync(
                fetch_shipment_activity_list(tenant_slug, shipment_id)
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "appointment_scheduling prepare activity fetch failed "
                "tenant_slug=%s shipment_id=%s error=%s",
                tenant_slug,
                shipment_id,
                exc,
            )
            return IngressPrepareResult(
                ok=False,
                skip_reason="turvo_activity_fetch_failed",
            )

        if activity_reason := evaluate_activity_gates(activity_json):
            return IngressPrepareResult(ok=False, skip_reason=activity_reason)

        load_id = fetched.load_id
        reference_number = fetched.reference_number

        skip_reason, contact = resolve_recipient_contact(
            tenant_settings=tenant_settings,
            shipment_payload=shipment_payload,
        )
        if skip_reason:
            logger.info(
                "appointment_scheduling prepare skipped tenant_slug=%s shipment_id=%s reason=%s",
                tenant_slug,
                shipment_id,
                skip_reason,
            )
            return IngressPrepareResult(ok=False, skip_reason=skip_reason)

        display_fields = appointment_scheduling_display_fields_from_payload(shipment_payload)
        upsert = self._shipments.upsert_from_turvo(
            tenant_id=tenant_uuid,
            turvo_shipment_id=shipment_id,
            load_id=load_id,
            metadata={"reference_number": reference_number},
            turvo_payload=shipment_payload,
            display_fields=display_fields,
        )
        if not upsert.get("success"):
            return IngressPrepareResult(ok=False, skip_reason="lifecycle_create_failed")

        shipments_row_id = str(upsert.get("shipments_row_id") or "").strip()
        if not shipments_row_id:
            return IngressPrepareResult(ok=False, skip_reason="lifecycle_create_failed")

        self._location_link.try_link_from_turvo_shipment_payload(
            shipment_payload,
            shipments_row_id=shipments_row_id,
        )

        customer_name = delivery_stop_name_from_payload(shipment_payload) or None

        try:
            lifecycle_id = self._lifecycle.create_appointment_scheduling_lifecycle(
                tenant_id=tenant_slug,
                shipments_row_id=shipments_row_id,
                workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
                lifecycle_id=existing_lifecycle_id or None,
            )
        except ValueError:
            return IngressPrepareResult(ok=False, skip_reason="lifecycle_create_failed")

        return IngressPrepareResult(
            ok=True,
            workflow_lifecycle_id=lifecycle_id,
            shipments_row_id=shipments_row_id,
            reference_number=reference_number,
            load_id=load_id,
            shipment=None,
            customer_contact=contact,
            customer_name=customer_name,
        )


__all__ = (
    "IngressPrepareService",
    "IngressPrepareResult",
)
