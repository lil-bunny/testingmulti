"""Inbound driver-details email ingress."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import status
from fastapi.responses import JSONResponse

from app.core.logger import get_logger
from app.domain.status_parsing import sub_status_type_from_db
from app.domain.unipile_email import is_unipile_email_reply
from app.models.status import StatusSubType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    DRIVER_DETAILS_TERMINAL_SUB_STATUSES,
    RATECON_WORKFLOW,
)
from app.services.tenants_service import TenantsService
from app.services.unipile_tenant_resolution import UnipileTenantContext

logger = get_logger(__name__)

class IngressDriverDetailsInboundMixin:
    def _resolve_active_driver_details_lifecycle_id(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        ) -> str | None:
        lifecycle_id = self._communications.find_active_lifecycle_id_for_thread(
            tenant_id=tenant_id,
            thread_id=thread_id,
            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,
        )
        if lifecycle_id:
            return lifecycle_id

        rows = self._communications.find_shipment_context_for_thread(
            tenant_id=tenant_id,
            thread_id=thread_id,
        )
        if not rows:
            return None

        distinct_shipments = {
            self._clean(row.get("shipments_row_id"))
            for row in rows
            if self._clean(row.get("shipments_row_id"))
        }
        if len(distinct_shipments) > 1:
            logger.warning(
                "driver_details ingress: multiple shipments on thread shipments=%s",
                sorted(distinct_shipments),
            )

        shipments_row_id = self._clean(rows[0].get("shipments_row_id"))
        if not shipments_row_id:
            return None

        lifecycle_id = self._lifecycle_service.find_active_driver_assignment_lifecycle_id(
            tenant_id=tenant_id,
            shipment_id=shipments_row_id,
        )
        if not lifecycle_id:
            return None

        row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
        sub = sub_status_type_from_db(row.get("sub_status"))
        if sub in DRIVER_DETAILS_TERMINAL_SUB_STATUSES:
            return None

        return lifecycle_id

    def _build_driver_details_workflow_payload(

        self,

        *,

        tenant_uuid: str,

        tenant_slug: str,

        lifecycle_id: str,

        thread_id: str,

        payload: dict[str, Any],

        communication_id: str | None,

        ) -> dict[str, Any] | None:

        correlation = self._lifecycle_service.read_correlation_by_id(lifecycle_id)

        shipments_row_id = self._clean(

            (correlation or {}).get("shipment_id")

        )

        if not shipments_row_id:

            return None

        ship_row = self._shipments.get_by_id(

            tenant_id=tenant_uuid,

            shipment_id=shipments_row_id,

        )

        metadata = (ship_row or {}).get("metadata") or {}

        load_id = self._clean(metadata.get("load_id"))

        turvo_shipment_id = self._clean((ship_row or {}).get("shipment_number"))

        ratecon_lc = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_uuid,

            workflow_name=RATECON_WORKFLOW,

            shipment_id=shipments_row_id,

        )

        ratecon_workflow_lifecycle_id = self._clean(ratecon_lc.get("lifecycle_id"))

        if not all((load_id, turvo_shipment_id, ratecon_workflow_lifecycle_id)):

            return None

        return {

            "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            "tenant_id": tenant_uuid,

            "tenant_slug": tenant_slug,

            "workflow_lifecycle_id": lifecycle_id,

            "thread_id": thread_id,

            "shipments_row_id": shipments_row_id,

            "shipment_id": turvo_shipment_id,

            "load_id": load_id,

            "ratecon_workflow_lifecycle_id": ratecon_workflow_lifecycle_id,

            "communication_id": communication_id,

            "body": payload.get("body"),

            "subject": payload.get("subject"),

        }

    def enqueue_driver_assignment_event_and_link(

        self,

        *,

        tenant_uuid: str,

        tenant_slug: str,

        workflow_lifecycle_id: str,

        payload: dict[str, Any],

        event_type: str,

        communication_id: str | None = None,

        thread_id: str | None = None,

        ) -> str:

        execution_id = str(uuid.uuid4())

        body = {**payload, "event_type": event_type, "execution_id": execution_id}

        from app.tasks.workflows import run_workflow_async

        run_workflow_async.apply_async(

            kwargs={

                "tenant_slug": tenant_slug,

                "workflow_name": DRIVER_ASSIGNMENT_WORKFLOW,

                "payload": body,

            }

        )

        self._runs_service.record_workflow_run(

            run_id=execution_id,

            tenant_id=tenant_uuid,

            event_type=event_type,

            workflow_lifecycle_id=workflow_lifecycle_id,

        )

        if communication_id:

            self._communications.link_inbound_to_workflow_run(

                communication_id=communication_id,

                workflow_run_id=execution_id,

            )

        if thread_id:

            self._communications.link_workflow_run_to_thread(

                tenant_id=tenant_uuid,

                thread_id=thread_id,

                workflow_run_id=execution_id,

            )

        logger.info(

            "driver_assignment email queued execution_id=%s event_type=%s lifecycle_id=%s",

            execution_id,

            event_type,

            workflow_lifecycle_id,

        )

        return execution_id

    def try_driver_details_email_received(

        self,

        *,

        payload: dict[str, Any],

        tenant: UnipileTenantContext,

        communication_id: str | None = None,

        ) -> JSONResponse | None:

        if not is_unipile_email_reply(payload):

            return None

        thread_id = self._clean(payload.get("thread_id"))

        if not thread_id:

            return None

        tenant_row = TenantsService().get_by_slug(tenant.tenant_slug)

        tenant_settings = (tenant_row or {}).get("settings") or {}

        if not self._is_process_enabled(tenant_settings):

            return None

        lifecycle_id = self._resolve_active_driver_details_lifecycle_id(
            tenant_id=tenant.tenant_uuid,
            thread_id=thread_id,
        )

        if not lifecycle_id:
            logger.info(
                "driver_details_email_received skipped no_active_lifecycle "
                "thread_id=%s tenant=%s",
                thread_id,
                tenant.tenant_uuid,
            )
            return None

        lifecycle_row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}

        sub = sub_status_type_from_db(lifecycle_row.get("sub_status"))

        if sub in (

            StatusSubType.DETAILS_RECEIVED,

            StatusSubType.UPLOADED_TO_TMS,

        ):

            return JSONResponse(

                status_code=status.HTTP_200_OK,

                content={

                    "message": "lifecycle terminal; driver details not processed",

                    "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

                    "workflow_lifecycle_id": lifecycle_id,

                },

            )

        workflow_payload = self._build_driver_details_workflow_payload(

            tenant_uuid=tenant.tenant_uuid,

            tenant_slug=tenant.tenant_slug,

            lifecycle_id=lifecycle_id,

            thread_id=thread_id,

            payload=payload,

            communication_id=communication_id,

        )

        if workflow_payload is None:

            logger.warning(

                "driver_details_email_received skipped missing correlation lifecycle_id=%s thread_id=%s",

                lifecycle_id,

                thread_id,

            )

            return None

        execution_id = self.enqueue_driver_assignment_event_and_link(

            tenant_uuid=tenant.tenant_uuid,

            tenant_slug=tenant.tenant_slug,

            workflow_lifecycle_id=lifecycle_id,

            payload=workflow_payload,

            event_type=WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            communication_id=communication_id,

            thread_id=thread_id,

        )

        return JSONResponse(

            status_code=status.HTTP_200_OK,

            content={

                "message": "success",

                "execution_id": execution_id,

                "event_type": WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,

            },

        )
