"""Validate and enqueue appointment scheduling draft send."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.appointment_scheduling.constants import APPOINTMENT_SCHEDULING_WORKFLOW
from app.domain.error_catalog import BusinessError
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


class SendConflictError(Exception):
    """Lifecycle is not ready to send (already queued/sent or wrong phase)."""


class SendService:
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

    def validate_and_enqueue_draft_send(
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

        claim = self._lifecycle.claim_appointment_draft_send_queued(
            lifecycle_id=wl_id,
            expected_tenant_id=caller_tenant_uuid,
        )
        if claim == "not_found":
            raise ValueError("lifecycle_not_found")
        if claim == "invalid_status":
            raise ValueError("invalid_lifecycle_status")
        if claim == BusinessError.SCHEDULING_DRAFT_NOT_READY.value:
            raise ValueError(BusinessError.SCHEDULING_DRAFT_NOT_READY.value)
        if claim == "conflict":
            raise SendConflictError(
                "Draft email was already sent or lifecycle is not ready to send"
            )
        if claim != "claimed":
            raise SendConflictError(
                "Draft email was already sent or lifecycle is not ready to send"
            )

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
    }
    result = LifecycleRunSerializerService().enqueue(
        tenant_slug=tenant_slug,
        workflow_name=APPOINTMENT_SCHEDULING_WORKFLOW,
        payload=body,
    )
    logger.info(
        "appointment_draft_send serialize status=%s celery_task_id=%s execution_id=%s lifecycle_id=%s",
        result.status,
        result.celery_task_id,
        execution_id,
        payload.get("workflow_lifecycle_id"),
    )
    return execution_id


__all__ = (
    "SendConflictError",
    "SendService",
    "enqueue_appointment_draft_send",
)
