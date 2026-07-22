"""T3RA inbound driver-details email ingress (Unipile ``mail_received`` replies)."""

from __future__ import annotations

import uuid
from typing import Any, TYPE_CHECKING

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.status_parsing import sub_status_type_from_db
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.domain.unipile_email import is_unipile_email_reply
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    DRIVER_DETAILS_TERMINAL_SUB_STATUSES,
    RATECON_WORKFLOW,
)
from app.services.shipments_service import ShipmentsService
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService

if TYPE_CHECKING:
    from app.services.unipile_tenant_resolution import UnipileTenantContext
    from collections.abc import Callable

logger = get_logger(__name__)


class DriverDetailsEmailIngressService:
    """Resolve driver-details replies on active driver_assignment lifecycles and enqueue."""

    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        runs_service: WorkflowRunsService | None = None,
        shipments_service: ShipmentsService | None = None,
        communications_service: CommunicationsService | None = None,
        process_enabled_check: Callable[[dict[str, Any] | None], bool] | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()
        self._runs_service = runs_service or WorkflowRunsService()
        self._shipments = shipments_service or ShipmentsService()
        self._communications = communications_service or CommunicationsService()
        self._process_enabled_check = process_enabled_check or self._is_driver_assignment_enabled

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @staticmethod
    def _is_driver_assignment_enabled(tenant_settings: dict[str, Any] | None) -> bool:
        return DRIVER_ASSIGNMENT_WORKFLOW in enabled_processes_from_settings(
            tenant_settings
        )

    def resolve_active_driver_details_lifecycle_id(
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

        thread_context_rows = self._communications.find_shipment_context_for_thread(
            tenant_id=tenant_id,
            thread_id=thread_id,
        )
        if not thread_context_rows:
            return None

        distinct_shipments = {
            self._clean(row.get("shipments_row_id"))
            for row in thread_context_rows
            if self._clean(row.get("shipments_row_id"))
        }
        if len(distinct_shipments) > 1:
            logger.warning(
                "driver_details ingress: multiple shipments on thread shipments=%s",
                sorted(distinct_shipments),
            )

        shipments_row_id = self._clean(thread_context_rows[0].get("shipments_row_id"))
        if not shipments_row_id:
            return None

        lifecycle_id = self._lifecycle_service.find_active_driver_assignment_lifecycle_id(
            tenant_id=tenant_id,
            shipment_id=shipments_row_id,
        )
        if not lifecycle_id:
            return None

        lifecycle_row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
        sub_status = sub_status_type_from_db(lifecycle_row.get("sub_status"))
        if sub_status in DRIVER_DETAILS_TERMINAL_SUB_STATUSES:
            return None

        return lifecycle_id

    def build_driver_details_workflow_payload(
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
        shipments_row_id = self._clean((correlation or {}).get("shipment_id"))
        if not shipments_row_id:
            return None

        shipment_row = self._shipments.get_by_id(
            tenant_id=tenant_uuid,
            shipment_id=shipments_row_id,
        )
        metadata = (shipment_row or {}).get("metadata") or {}
        load_id = self._clean(metadata.get("load_id"))
        turvo_shipment_id = self._clean((shipment_row or {}).get("shipment_number"))

        ratecon_lifecycle_lookup = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tenant_uuid,
            workflow_name=RATECON_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        ratecon_workflow_lifecycle_id = self._clean(
            ratecon_lifecycle_lookup.get("lifecycle_id")
        )

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
        """
        Serialize-enqueue driver_assignment and link run/comms to the lifecycle.

        Lifecycle id is already known (driver-details reply path); stamps it on
        the payload, records the workflow run, then links communication/thread.
        """
        execution_id = str(uuid.uuid4())
        workflow_body = {**payload, "event_type": event_type, "execution_id": execution_id}

        from app.services.lifecycle_run_serializer_service import (
            LifecycleRunSerializerService,
        )

        workflow_body["workflow_lifecycle_id"] = workflow_lifecycle_id
        lifecycle_run_serializer_service = LifecycleRunSerializerService()
        lifecycle_run_serializer_service.enqueue(
            tenant_slug=tenant_slug,
            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,
            payload=workflow_body,
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
    ) -> IngressResult | None:
        if not is_unipile_email_reply(payload):
            return None

        thread_id = self._clean(payload.get("thread_id"))
        if not thread_id:
            return None

        tenant_row = TenantsService().get_by_slug(tenant.tenant_slug)
        tenant_settings = (tenant_row or {}).get("settings") or {}

        if not self._process_enabled_check(tenant_settings):
            return None

        lifecycle_id = self.resolve_active_driver_details_lifecycle_id(
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
        sub_status = sub_status_type_from_db(lifecycle_row.get("sub_status"))
        if sub_status in DRIVER_DETAILS_TERMINAL_SUB_STATUSES:
            return IngressResult(
                outcome="skipped",
                event_type=WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,
                reason="lifecycle terminal; driver details not processed",
            )

        workflow_payload = self.build_driver_details_workflow_payload(
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            lifecycle_id=lifecycle_id,
            thread_id=thread_id,
            payload=payload,
            communication_id=communication_id,
        )
        if workflow_payload is None:
            logger.warning(
                "driver_details_email_received skipped missing correlation "
                "lifecycle_id=%s thread_id=%s",
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
        return IngressResult(
            outcome="enqueued",
            event_type=WorkflowRunEventType.DRIVER_DETAILS_EMAIL_RECEIVED.value,
            execution_ids=(execution_id,),
        )
