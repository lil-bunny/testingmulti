"""Turvo SHIPMENT_UPDATE ingress for appointment_scheduling.

Webhook path: tenant/process gates, Turvo shipment+activity filters, sheet/recipient
gate, shipment upsert, lifecycle create, then Celery enqueue. Worker prepare is a
no-op when lifecycle ids are already on the payload.
"""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.ingress_constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.domain.appointment_scheduling.skip_reasons import resolve_scheduling_error
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
from app.services.appointment_scheduling.ingress_prepare_service import (
    AppointmentSchedulingIngressPrepareService,
)
from app.services.appointment_scheduling.ingress_types import IngressHandleResult
from app.services.appointment_scheduling.lifecycle_service import (
    AppointmentSchedulingLifecycleService,
)
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.turvo_scheduling_ingress import parse_shipment_update_webhook

logger = get_logger(__name__)


class AppointmentSchedulingIngressService:
    def __init__(
        self,
        *,
        tenants_service: TenantsService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
        prepare_service: AppointmentSchedulingIngressPrepareService | None = None,
        scheduling_lifecycle_service: AppointmentSchedulingLifecycleService | None = None,
    ) -> None:
        self._tenants = tenants_service or TenantsService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._prepare = prepare_service or AppointmentSchedulingIngressPrepareService()
        self._scheduling_lifecycle = (
            scheduling_lifecycle_service or AppointmentSchedulingLifecycleService()
        )

    @staticmethod
    def _skip(
        *,
        skip_reason: str,
        tenant_slug: str,
        shipment_id: str | None = None,
    ) -> IngressHandleResult:
        resolved = resolve_scheduling_error(skip_reason)
        if resolved is not None:
            catalog, message = resolved
            logger.info(
                "appointment_scheduling ingress skipped tenant_slug=%s shipment_id=%s "
                "reason=%s error_code=%s error_category=%s error_description=%s",
                tenant_slug,
                shipment_id,
                skip_reason,
                catalog.value,
                catalog.category.value,
                message,
            )
        else:
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

        payload = {
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "shipment_id": parsed.shipment_id,
            "load_id": fetched.load_id,
            "reference_number": fetched.reference_number,
            "shipment": shipment_payload,
        }

        prepare_result = self._prepare.prepare_pickup_changed(
            tenant_slug=tenant_slug,
            tenant_id=tenant_uuid,
            tenant_settings=tenant_settings,
            payload=payload,
        )
        if not prepare_result.ok:
            return self._skip(
                skip_reason=prepare_result.skip_reason or "lifecycle_create_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        lifecycle_id = str(prepare_result.workflow_lifecycle_id or "").strip()
        if not lifecycle_id:
            return self._skip(
                skip_reason="lifecycle_create_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        payload["workflow_lifecycle_id"] = lifecycle_id
        payload["shipments_row_id"] = prepare_result.shipments_row_id
        if prepare_result.customer_name:
            payload["customer_name"] = prepare_result.customer_name
        if prepare_result.customer_contact is not None:
            payload["customer_contact"] = prepare_result.customer_contact.model_dump(
                mode="json"
            )

        try:
            execution_id = enqueue_appointment_scheduling_pickup_changed(
                tenant_slug=tenant_slug,
                payload=payload,
            )
        except Exception:
            logger.exception(
                "appointment_scheduling enqueue failed tenant_slug=%s shipment_id=%s",
                tenant_slug,
                parsed.shipment_id,
            )
            self._scheduling_lifecycle.mark_restartable_skip(
                lifecycle_id,
                "enqueue_failed",
                tenant_id=tenant_uuid,
            )
            return self._skip(
                skip_reason="enqueue_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        logger.info(
            "appointment_scheduling ingress enqueued tenant_slug=%s shipment_id=%s execution_id=%s",
            tenant_slug,
            parsed.shipment_id,
            execution_id,
        )
        return IngressHandleResult(
            handled=True,
            enqueued=True,
            execution_id=execution_id,
        )
