"""Turvo SHIPMENT_UPDATE ingress for appointment_scheduling.

Webhook path: cheap tenant/process/parse/duplicate gates, then serializer enqueue.
Worker ``WorkflowService.run`` calls ``prepare_pickup_changed`` before LangGraph.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.domain.appointment_scheduling.scheduling_reference import is_diamond_scheduling_reference
from app.domain.error_catalog import BusinessError, format_error_message, resolve_error_code
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.domain.tenant_settings.tms import has_tms_partner_config
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService
from app.services.shipments_service import ShipmentsService
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.integrations.turvo.shipments import is_multi_stop_shipment
from app.tools.appointment_scheduling.ingress import (
    ParsedShipmentUpdateWebhook,
    load_id_from_turvo_shipment,
    parse_shipment_update_webhook,
    pickup_changed_in_activity_delta,
    reference_number_from_turvo_shipment,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class IngressHandleResult:
    """Outcome of Turvo SHIPMENT_UPDATE scheduling ingress."""

    handled: bool
    enqueued: bool = False
    skip_reason: str | None = None
    execution_id: str | None = None


@dataclass(frozen=True)
class FetchedSchedulingIngressData:
    reference_number: str
    load_id: str


class IngressService:
    def __init__(
        self,
        *,
        tenants_service: TenantsService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._tenants = tenants_service or TenantsService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._shipments = shipments_service or ShipmentsService()

    @staticmethod
    def _skip(
        *,
        skip_reason: str,
        tenant_slug: str,
        shipment_id: str | None = None,
    ) -> IngressHandleResult:
        catalog = resolve_error_code(skip_reason)
        if catalog is not None:
            logger.info(
                "appointment_scheduling ingress skipped tenant_slug=%s shipment_id=%s "
                "reason=%s error_code=%s error_category=%s error_description=%s",
                tenant_slug,
                shipment_id,
                skip_reason,
                catalog.value,
                catalog.category.value,
                format_error_message(catalog),
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

        execution_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "shipment_id": parsed.shipment_id,
            "event_type": WorkflowRunEventType.TURVO_PICKUP_CHANGED.value,
            "execution_id": execution_id,
            "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
        }
        load_id = str(parsed.load_id or "").strip()
        if load_id:
            payload["load_id"] = load_id

        try:
            serializer = LifecycleRunSerializerService()
            shipments_row = self._shipments.get_by_shipment_number(
                tenant_id=tenant_uuid,
                shipment_number=parsed.shipment_id,
            )
            if shipments_row:
                row_id = str(shipments_row.get("id") or "").strip()
                if row_id:
                    payload["shipments_row_id"] = row_id
                result = serializer.resolve_then_enqueue(
                    tenant_id=tenant_uuid,
                    tenant_slug=tenant_slug,
                    workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
                    payload=payload,
                )
                ingress_path = "resolve_then_enqueue"
            else:
                payload["workflow_lifecycle_id"] = (
                    self._lifecycle.deterministic_pickup_lifecycle_id(
                        tenant_id=tenant_uuid,
                        shipment_number=parsed.shipment_id,
                    )
                )
                result = serializer.enqueue(
                    tenant_slug=tenant_slug,
                    workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
                    payload=payload,
                )
                ingress_path = "enqueue_stub"
        except Exception:
            logger.exception(
                "appointment_scheduling enqueue failed tenant_slug=%s shipment_id=%s",
                tenant_slug,
                parsed.shipment_id,
            )
            return self._skip(
                skip_reason="enqueue_failed",
                tenant_slug=tenant_slug,
                shipment_id=parsed.shipment_id,
            )

        logger.info(
            "appointment_scheduling ingress serialize status=%s celery_task_id=%s "
            "execution_id=%s lifecycle_id=%s shipment_id=%s ingress_path=%s",
            result.status,
            result.celery_task_id,
            execution_id,
            result.lifecycle_id,
            parsed.shipment_id,
            ingress_path,
        )
        return IngressHandleResult(
            handled=True,
            enqueued=True,
            execution_id=execution_id,
        )


def evaluate_process_enabled(tenant_settings: dict | None) -> str | None:
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
        return BusinessError.ASCEND_MISSING_REFERENCE.value, None
    if not is_diamond_scheduling_reference(reference_number):
        return "non_diamond_customer", None

    load_id = (webhook_load_id or "").strip() or load_id_from_turvo_shipment(shipment_payload) or ""
    if not load_id:
        return "missing_load_id", None

    return None, FetchedSchedulingIngressData(
        reference_number=reference_number,
        load_id=load_id,
    )


__all__ = [
    "APPOINTMENT_SCHEDULING_WORKFLOW",
    "IngressService",
    "FetchedSchedulingIngressData",
    "IngressHandleResult",
    "evaluate_activity_gates",
    "evaluate_parsed_webhook",
    "evaluate_process_enabled",
    "evaluate_shipment_gates",
    "evaluate_turvo_configured",
]
