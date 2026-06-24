"""Ratecon tail enqueue and prepare (layers 1–2)."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.models.tenants import TenantSlug
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    PREPARE_REQUIRED_KEYS,
    EnqueueResult,
    PrepareResult,
)

logger = get_logger(__name__)

class IngressRateconMixin:
    def try_enqueue_from_ratecon_state(self, state) -> EnqueueResult:

        """Layer 1: silent skip or enqueue Celery from ratecon graph tail."""

        data = state.data if hasattr(state, "data") else {}

        tenant_id = self._clean(getattr(state, "tenant_id", None) or data.get("tenant_id"))

        tenant_slug = self._clean(data.get("tenant_slug")) or TenantSlug.T3RA.value

        tenant_settings = data.get("tenant_settings") or {}

        if data.get("error"):

            return EnqueueResult(enqueued=False, skip_reason="workflow_error")

        if not self._ratecon_upload_success(data):

            return EnqueueResult(

                enqueued=False,

                skip_reason="ratecon_upload_not_succeeded",

            )

        if not self._ratecon_analysis_success(data):

            return EnqueueResult(

                enqueued=False,

                skip_reason="ratecon_analysis_not_stored",

            )

        shipments_row_id = self._clean(data.get("shipments_row_id"))

        load_id = self._clean(data.get("load_id"))

        shipment_id = self._clean(data.get("shipment_id"))

        ratecon_workflow_lifecycle_id = self._clean(data.get("workflow_lifecycle_id"))

        if not tenant_id or not all(

            (shipments_row_id, load_id, shipment_id, ratecon_workflow_lifecycle_id)

        ):

            return EnqueueResult(

                enqueued=False,

                skip_reason="missing_correlation_keys",

            )

        thread_id = self._clean(data.get("thread_id"))

        if not thread_id and ratecon_workflow_lifecycle_id:

            thread_id = self._communications.resolve_thread_for_lifecycle(

                tenant_id=tenant_id,

                workflow_lifecycle_id=ratecon_workflow_lifecycle_id,

            )

        if not thread_id:

            return EnqueueResult(enqueued=False, skip_reason="missing_thread_id")

        payload = {

            "event_type": WorkflowRunEventType.RATECON_COMPLETED.value,

            "tenant_id": tenant_id,

            "tenant_slug": tenant_slug,

            "shipment_id": shipment_id,

            "shipments_row_id": shipments_row_id,

            "load_id": load_id,

            "thread_id": thread_id,

            "ratecon_workflow_lifecycle_id": ratecon_workflow_lifecycle_id,

            "communication_id": self._clean(data.get("communication_id")),

        }

        turvo_payload = data.get("shipment")

        eligibility_skip = self._driver_request_skip_reason(turvo_payload)

        if eligibility_skip:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                eligibility_skip,

                shipment_id,

                load_id,

            )

            self._log_layer1_skip_on_ratecon(

                state=state,

                tenant_id=tenant_id,

                skip_reason=eligibility_skip,

                payload=payload,

            )

            return EnqueueResult(enqueued=False, skip_reason=eligibility_skip)

        pickup_skip, pickup_fields = self._enrich_pickup_from_turvo_payload(

            turvo_payload

        )

        if pickup_skip:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                pickup_skip,

                shipment_id,

                load_id,

            )

            self._log_layer1_skip_on_ratecon(

                state=state,

                tenant_id=tenant_id,

                skip_reason=pickup_skip,

                payload=payload,

                pickup_fields=pickup_fields,

            )

            return EnqueueResult(enqueued=False, skip_reason=pickup_skip)

        payload.update(pickup_fields)

        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=payload,

        )

        if skip_reason:

            logger.info(

                "driver_assignment enqueue skipped reason=%s shipment_id=%s load_id=%s",

                skip_reason,

                shipment_id,

                load_id,

            )

            return EnqueueResult(enqueued=False, skip_reason=skip_reason)

        execution_id = str(uuid.uuid4())

        payload["execution_id"] = execution_id

        from app.tasks.workflows import run_workflow_async

        task = run_workflow_async.apply_async(

            kwargs={

                "tenant_slug": tenant_slug,

                "workflow_name": DRIVER_ASSIGNMENT_WORKFLOW,

                "payload": payload,

            }

        )

        logger.info(

            "driver_assignment queued task_id=%s execution_id=%s ratecon_lifecycle_id=%s shipment_id=%s",

            task.id,

            execution_id,

            ratecon_workflow_lifecycle_id,

            shipment_id,

        )

        return EnqueueResult(

            enqueued=True,

            execution_id=execution_id,

            celery_task_id=task.id,

        )

    async def prepare_ratecon_completed_payload(

        self,

        *,

        tenant_id: str,

        tenant_slug: str,

        payload: dict[str, Any],

        ) -> PrepareResult:

        """Layer 2: validate parent ratecon state before driver lifecycle resolve."""

        tenant_settings = payload.get("tenant_settings") or {}

        missing = [

            key

            for key in PREPARE_REQUIRED_KEYS

            if not self._clean(payload.get(key))

        ]

        if missing:

            raise Exception(

                f"Missing required payload keys for 'driver_assignment': {missing}"

            )

        out = dict(payload)

        thread_id = self._resolve_thread_id(tenant_id=tenant_id, payload=out)

        if thread_id:

            out["thread_id"] = thread_id

        self._ensure_pickup_on_payload(out)

        eligibility_skip = self._driver_request_skip_reason(out.get("shipment"))

        if eligibility_skip:

            logger.info(

                "driver_assignment prepare skipped reason=%s tenant_slug=%s shipment_id=%s",

                eligibility_skip,

                tenant_slug,

                out.get("shipment_id"),

            )

            return PrepareResult(skipped=True, skip_reason=eligibility_skip)

        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=out,

        )

        if skip_reason:

            logger.info(

                "driver_assignment prepare skipped reason=%s tenant_slug=%s shipment_id=%s",

                skip_reason,

                tenant_slug,

                out.get("shipment_id"),

            )

            return PrepareResult(skipped=True, skip_reason=skip_reason)

        return PrepareResult(skipped=False, payload=out)
