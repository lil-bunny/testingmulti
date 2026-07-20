"""Turvo SHIPMENT_UPDATE ingress for appointment_scheduling."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.ingress_constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.integrations.turvo.activity import fetch_shipment_activity_list
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import get_shipment
from app.services.appointment_scheduling.enqueue import enqueue_appointment_scheduling_pickup_changed
from app.services.appointment_scheduling.ingress_gates import (
    evaluate_activity_gates,
    evaluate_parsed_webhook,
    evaluate_process_enabled,
    evaluate_shipment_gates,
    evaluate_turvo_configured,
)
from app.services.appointment_scheduling.ingress_types import IngressHandleResult
from app.services.shipments_service import ShipmentsService
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.turvo_scheduling_ingress import parse_shipment_update_webhook

logger = get_logger(__name__)


class AppointmentSchedulingIngressService:
    def __init__(
        self,
        *,
        tenants_service: TenantsService | None = None,
        shipments_service: ShipmentsService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._tenants = tenants_service or TenantsService()
        self._shipments = shipments_service or ShipmentsService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    @staticmethod
    def _skip(
        *,
        skip_reason: str,
        tenant_slug: str,
        shipment_id: str | None = None,
    ) -> IngressHandleResult:
        logger.info(
            "appointment_scheduling ingress skipped tenant_slug=%s shipment_id=%s reason=%s",
            tenant_slug,
            shipment_id,
            skip_reason,
        )
        return IngressHandleResult(handled=True, enqueued=False, skip_reason=skip_reason)

    async def handle_shipment_update(
        self,
        body: dict[str, Any],
        tenant_slug: str,
    ) -> IngressHandleResult:
        parsed = parse_shipment_update_webhook(body)
        if parsed is None:
            return IngressHandleResult(handled=False)

        tenant_row = self._tenants.get_by_slug(tenant_slug)
        if tenant_row is None:
            return self._skip(skip_reason="tenant_not_resolved", tenant_slug=tenant_slug)

        tenant_settings = tenant_row.get("settings") or {}
        tenant_uuid = str(tenant_row.get("id") or "").strip()
        if not tenant_uuid:
            return self._skip(
                skip_reason="tenant_not_resolved",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        if reason := evaluate_process_enabled(tenant_settings):
            return self._skip(
                skip_reason=reason,
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        if reason := evaluate_parsed_webhook(parsed):
            return self._skip(
                skip_reason=reason,
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        if reason := evaluate_turvo_configured(tenant_settings):
            return self._skip(
                skip_reason=reason,
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        if self._lifecycle.find_blocking_appointment_scheduling_lifecycle_id(
            tenant_id=tenant_slug,
            turvo_shipment_number=parsed.shipment_id,
            workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
        ):
            return self._skip(
                skip_reason="duplicate_lifecycle",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        try:
            activity_json = await fetch_shipment_activity_list(
                tenant_slug,
                parsed.shipment_id,
            )
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "appointment_scheduling activity fetch failed tenant_slug=%s shipment_id=%s error=%s",
                tenant_slug,
                parsed.shipment_id,
                exc,
            )
            return self._skip(
                skip_reason="turvo_activity_fetch_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        if reason := evaluate_activity_gates(activity_json):
            return self._skip(
                skip_reason=reason,
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        try:
            shipment_payload = await get_shipment(tenant_slug, parsed.shipment_id)
        except (TurvoApiError, ValueError) as exc:
            logger.warning(
                "appointment_scheduling shipment fetch failed tenant_slug=%s shipment_id=%s error=%s",
                tenant_slug,
                parsed.shipment_id,
                exc,
            )
            return self._skip(
                skip_reason="turvo_shipment_fetch_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        reason, fetched = evaluate_shipment_gates(
            shipment_payload,
            webhook_load_id=parsed.load_id,
        )
        if reason or fetched is None:
            return self._skip(
                skip_reason=reason or "missing_reference_number",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        upsert = self._shipments.upsert_from_turvo(
            tenant_id=tenant_uuid,
            turvo_shipment_id=parsed.shipment_id,
            load_id=fetched.load_id,
            metadata={"reference_number": fetched.reference_number},
            turvo_payload=shipment_payload,
        )
        if not upsert.get("success"):
            return self._skip(
                skip_reason="lifecycle_create_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        shipments_row_id = str(upsert.get("shipments_row_id") or "").strip()
        if not shipments_row_id:
            return self._skip(
                skip_reason="lifecycle_create_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        try:
            lifecycle_id = self._lifecycle.create_appointment_scheduling_lifecycle(
                tenant_id=tenant_slug,
                shipments_row_id=shipments_row_id,
                workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
            )
        except ValueError:
            return self._skip(
                skip_reason="lifecycle_create_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        payload = {
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "shipment_id": parsed.shipment_id,
            "load_id": fetched.load_id,
            "shipments_row_id": shipments_row_id,
            "workflow_lifecycle_id": lifecycle_id,
            "reference_number": fetched.reference_number,
        }

        try:
            execution_id = enqueue_appointment_scheduling_pickup_changed(
                tenant_slug=tenant_slug,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "appointment_scheduling enqueue failed tenant_slug=%s shipment_id=%s lifecycle_id=%s",
                tenant_slug,
                parsed.shipment_id,
                lifecycle_id,
            )
            return self._skip(
                skip_reason="enqueue_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        logger.info(
            "appointment_scheduling ingress enqueued tenant_slug=%s shipment_id=%s lifecycle_id=%s execution_id=%s",
            tenant_slug,
            parsed.shipment_id,
            lifecycle_id,
            execution_id,
        )
        return IngressHandleResult(
            handled=True,
            enqueued=True,
            execution_id=execution_id,
        )
