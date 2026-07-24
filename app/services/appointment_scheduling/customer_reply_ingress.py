"""T3RA inbound appointment scheduling customer-reply email ingress."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.utils import clean_optional_str
from app.domain.appointment_scheduling.constants import (
    APPOINTMENT_SCHEDULING_WORKFLOW,
    SCHEDULING_REPLY_TERMINAL_STATUSES,
    SCHEDULING_REPLY_TERMINAL_SUB_STATUSES,
)
from app.domain.ingress_result import IngressResult
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.domain.unipile_email import is_unipile_email_reply
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.services.shipments_service import ShipmentsService
from app.services.tenants_service import TenantsService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService
from app.tools.appointment_scheduling.draft_email import (
    is_del_appt_req_subject,
    parse_del_appt_req_subject_token,
)

logger = get_logger(__name__)


class CustomerReplyIngressService:
    """Resolve customer replies on active appointment_scheduling lifecycles and enqueue."""

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
        self._process_enabled_check = (
            process_enabled_check or self._is_appointment_scheduling_enabled
        )

    @staticmethod
    def _is_appointment_scheduling_enabled(tenant_settings: dict[str, Any] | None) -> bool:
        return APPOINTMENT_SCHEDULING_WORKFLOW in enabled_processes_from_settings(
            tenant_settings
        )

    def _lifecycle_is_terminal(self, lifecycle_row: dict[str, Any]) -> bool:
        status = status_type_from_db(lifecycle_row.get("status"))
        sub_status = sub_status_type_from_db(lifecycle_row.get("sub_status"))
        if status in SCHEDULING_REPLY_TERMINAL_STATUSES:
            return True
        if sub_status in SCHEDULING_REPLY_TERMINAL_SUB_STATUSES:
            return True
        return False

    def resolve_active_reply_lifecycle_id(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        subject: str | None = None,
    ) -> str | None:
        lifecycle_id = self._communications.find_active_lifecycle_id_for_thread(
            tenant_id=tenant_id,
            thread_id=thread_id,
            workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
        )
        if lifecycle_id:
            row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
            sub_status = sub_status_type_from_db(row.get("sub_status"))
            if sub_status != StatusSubType.AWAITING_CUSTOMER_REPLY:
                return None
            if self._lifecycle_is_terminal(row):
                return None
            return lifecycle_id

        thread_context_rows = self._communications.find_shipment_context_for_thread(
            tenant_id=tenant_id,
            thread_id=thread_id,
        )
        if thread_context_rows:
            shipments_row_id = clean_optional_str(thread_context_rows[0].get("shipments_row_id"))
            if shipments_row_id:
                lifecycle_id = self._lifecycle_service.find_awaiting_customer_reply_lifecycle_id(
                    tenant_id=tenant_id,
                    shipments_row_id=shipments_row_id,
                )
                if lifecycle_id:
                    row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
                    if not self._lifecycle_is_terminal(row):
                        return lifecycle_id

        if is_del_appt_req_subject(subject):
            token = parse_del_appt_req_subject_token(subject)
            if token:
                lifecycle_id = (
                    self._lifecycle_service.find_awaiting_customer_reply_by_appt_subject_token(
                        tenant_id=tenant_id,
                        subject_token=token,
                    )
                )
                if lifecycle_id:
                    row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
                    if not self._lifecycle_is_terminal(row):
                        return lifecycle_id

        return None

    def build_reply_workflow_payload(
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
        shipments_row_id = clean_optional_str((correlation or {}).get("shipment_id"))
        if not shipments_row_id:
            return None

        shipment_row = self._shipments.get_by_id(
            tenant_id=tenant_uuid,
            shipment_id=shipments_row_id,
        )
        metadata = (shipment_row or {}).get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}

        reference_number = clean_optional_str(
            metadata.get("reference_number")
            or (shipment_row or {}).get("shipment_number")
        )
        customer_name = clean_optional_str(
            (shipment_row or {}).get("customer_name")
            or metadata.get("customer_name")
        )
        turvo_shipment_id = clean_optional_str((shipment_row or {}).get("shipment_number"))
        load_id = clean_optional_str(metadata.get("load_id"))

        if not turvo_shipment_id:
            return None

        return {
            "event_type": WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value,
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "workflow_lifecycle_id": lifecycle_id,
            "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
            "thread_id": thread_id,
            "shipments_row_id": shipments_row_id,
            "shipment_id": turvo_shipment_id,
            "load_id": load_id,
            "reference_number": reference_number,
            "customer_name": customer_name,
            "communication_id": communication_id,
        }

    def enqueue_reply_event_and_link(
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
        workflow_body = {**payload, "event_type": event_type, "execution_id": execution_id}

        from app.tasks.workflows import run_workflow_async

        run_workflow_async.apply_async(
            kwargs={
                "tenant_slug": tenant_slug,
                "workflow_name": APPOINTMENT_SCHEDULING_WORKFLOW,
                "payload": workflow_body,
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
                workflow_lifecycle_id=workflow_lifecycle_id,
            )

        if thread_id:
            self._communications.link_workflow_run_to_thread(
                tenant_id=tenant_uuid,
                thread_id=thread_id,
                workflow_run_id=execution_id,
                workflow_lifecycle_id=workflow_lifecycle_id,
            )

        logger.info(
            "appointment_scheduling reply queued execution_id=%s lifecycle_id=%s",
            execution_id,
            workflow_lifecycle_id,
        )
        return execution_id

    def try_customer_reply_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None = None,
    ) -> IngressResult | None:
        if not is_unipile_email_reply(payload):
            return None

        thread_id = clean_optional_str(payload.get("thread_id"))
        if not thread_id:
            return None

        tenants = TenantsService()
        tenant_row = tenants.get_by_slug(tenant.tenant_slug)
        tenant_settings = (tenant_row or {}).get("settings") or {}

        if not self._process_enabled_check(tenant_settings):
            return None

        lifecycle_id = self.resolve_active_reply_lifecycle_id(
            tenant_id=tenant.tenant_uuid,
            thread_id=thread_id,
            subject=clean_optional_str(payload.get("subject")),
        )
        if not lifecycle_id:
            logger.info(
                "appointment_customer_reply skipped no_active_lifecycle thread_id=%s tenant=%s",
                thread_id,
                tenant.tenant_uuid,
            )
            return None

        lifecycle_row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id) or {}
        if self._lifecycle_is_terminal(lifecycle_row):
            return IngressResult(
                outcome="skipped",
                event_type=WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value,
                reason="lifecycle terminal",
            )

        workflow_payload = self.build_reply_workflow_payload(
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            lifecycle_id=lifecycle_id,
            thread_id=thread_id,
            payload=payload,
            communication_id=communication_id,
        )
        if workflow_payload is None:
            logger.warning(
                "appointment_customer_reply skipped missing correlation lifecycle_id=%s",
                lifecycle_id,
            )
            return None

        execution_id = self.enqueue_reply_event_and_link(
            tenant_uuid=tenant.tenant_uuid,
            tenant_slug=tenant.tenant_slug,
            workflow_lifecycle_id=lifecycle_id,
            payload=workflow_payload,
            event_type=WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value,
            communication_id=communication_id,
            thread_id=thread_id,
        )
        return IngressResult(
            outcome="enqueued",
            event_type=WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value,
            execution_ids=(execution_id,),
        )


__all__ = ("CustomerReplyIngressService",)
