"""Validate and enqueue appointment scheduling draft send."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.ingress_constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.models.status import StatusSubType, StatusType
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tasks.workflows import run_workflow_async

logger = get_logger(__name__)


class AppointmentSchedulingSendConflictError(Exception):
    """Lifecycle is not in appointment_draft_created (already sent or wrong phase)."""


class AppointmentSchedulingSendService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        tenants_service: TenantsService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._tenants = tenants_service or TenantsService()

    @staticmethod
    def _normalize_uuid(value: Any) -> str | None:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None

    @staticmethod
    def _email_draft_ready(metadata: Any) -> bool:
        if not isinstance(metadata, dict):
            return False
        draft = metadata.get("email_draft")
        if not isinstance(draft, dict):
            return False
        return bool(
            str(draft.get("to") or "").strip()
            and str(draft.get("subject") or "").strip()
            and str(draft.get("full_html") or "").strip()
        )

    def validate_and_enqueue(
        self,
        *,
        tenant_slug: str,
        workflow_lifecycle_id: str,
        actor_user_id: str,
        shipment_id: str | None = None,
    ) -> str:
        wl_id = str(workflow_lifecycle_id or "").strip()
        actor = str(actor_user_id or "").strip()
        if not wl_id:
            raise ValueError("workflow_lifecycle_id is required")
        if not actor:
            raise ValueError("actor_user_id is required")

        tenant_row = self._tenants.get_by_slug(tenant_slug)
        if tenant_row is None:
            raise ValueError("tenant_not_found")
        caller_tenant_uuid = self._normalize_uuid(tenant_row.get("id"))
        if not caller_tenant_uuid:
            raise ValueError("tenant_not_found")

        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        if not row:
            raise ValueError("lifecycle_not_found")

        row_tenant_uuid = self._normalize_uuid(row.get("tenant_id"))
        if row_tenant_uuid != caller_tenant_uuid:
            raise ValueError("lifecycle_not_found")

        status = str(row.get("status") or "").strip()
        sub_status = str(row.get("sub_status") or "").strip()
        if status != StatusType.PENDING_REVIEW.value:
            raise ValueError("invalid_lifecycle_status")
        if sub_status != StatusSubType.APPOINTMENT_DRAFT_CREATED.value:
            raise AppointmentSchedulingSendConflictError(
                "Draft email was already sent or lifecycle is not ready to send"
            )

        metadata = row.get("metadata") or {}
        if not self._email_draft_ready(metadata):
            raise ValueError("missing_email_draft")

        payload: dict[str, Any] = {
            "tenant_id": caller_tenant_uuid,
            "tenant_slug": tenant_slug,
            "workflow_lifecycle_id": wl_id,
            "actor_user_id": actor,
        }
        if shipment_id:
            payload["shipment_id"] = str(shipment_id).strip()

        return enqueue_appointment_draft_send(tenant_slug=tenant_slug, payload=payload)


def enqueue_appointment_draft_send(
    *,
    tenant_slug: str,
    payload: dict[str, Any],
) -> str:
    execution_id = str(uuid.uuid4())
    body = {
        **payload,
        "event_type": WorkflowRunEventType.APPOINTMENT_DRAFT_SEND.value,
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
        "appointment_draft_send queued task_id=%s execution_id=%s lifecycle_id=%s",
        task.id,
        execution_id,
        payload.get("workflow_lifecycle_id"),
    )
    return execution_id


__all__ = (
    "AppointmentSchedulingSendConflictError",
    "AppointmentSchedulingSendService",
    "enqueue_appointment_draft_send",
)
