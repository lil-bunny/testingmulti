"""Turvo SHIPMENT_UPDATE ingress for appointment_scheduling.

Webhook path: cheap tenant/process/parse/duplicate gates, then Celery enqueue with a
slim payload. Worker ``prepare_appointment_ingress`` owns Turvo fetch, activity and
sheet gates, shipment upsert, and lifecycle create.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.domain.appointment_scheduling.scheduling_reference import is_diamond_scheduling_reference
from app.domain.appointment_scheduling.skip_reasons import resolve_scheduling_error
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.domain.tenant_settings.tms import has_tms_partner_config
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async
from app.tools.appointment_scheduling.ingress import (
    ParsedShipmentUpdateWebhook,
    is_multi_stop_shipment,
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
    activity_json: dict
    shipment_payload: dict
    reference_number: str
    load_id: str


class IngressService:
    def __init__(
        self,
        *,
        tenants_service: TenantsService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._tenants = tenants_service or TenantsService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

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

        payload: dict[str, Any] = {
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "shipment_id": parsed.shipment_id,
        }
        load_id = str(parsed.load_id or "").strip()
        if load_id:
            payload["load_id"] = load_id

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


def enqueue_appointment_scheduling_pickup_changed(
    *,
    tenant_slug: str,
    payload: dict[str, Any],
) -> str:
    execution_id = str(uuid.uuid4())
    body = {
        **payload,
        "event_type": WorkflowRunEventType.TURVO_PICKUP_CHANGED.value,
        "execution_id": execution_id,
        "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
    }
    task = run_workflow_async.apply_async(
        kwargs={
            "tenant_slug": tenant_slug,
            "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
            "payload": body,
        }
    )
    logger.info(
        "appointment_scheduling ingress queued workflow task_id=%s execution_id=%s shipment_id=%s",
        task.id,
        execution_id,
        payload.get("shipment_id"),
    )
    return execution_id


__all__ = [
    "APPOINTMENT_SCHEDULING_WORKFLOW",
    "IngressService",
    "FetchedSchedulingIngressData",
    "IngressHandleResult",
    "enqueue_appointment_scheduling_pickup_changed",
    "evaluate_activity_gates",
    "evaluate_parsed_webhook",
    "evaluate_process_enabled",
    "evaluate_shipment_gates",
    "evaluate_turvo_configured",
]
