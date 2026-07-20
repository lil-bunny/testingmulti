"""Validate and enqueue appointment scheduling draft send."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.models.status import StatusSubType, StatusType
from app.services.appointment_scheduling.enqueue import enqueue_appointment_draft_send
from app.services.tenants_service import TenantsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

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

        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        if not row:
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

        tenant_row = self._tenants.get_by_slug(tenant_slug)
        if tenant_row is None:
            raise ValueError("tenant_not_found")
        tenant_uuid = str(tenant_row.get("id") or "").strip()
        if not tenant_uuid:
            raise ValueError("tenant_not_found")

        payload: dict[str, Any] = {
            "tenant_id": tenant_uuid,
            "tenant_slug": tenant_slug,
            "workflow_lifecycle_id": wl_id,
            "actor_user_id": actor,
        }
        if shipment_id:
            payload["shipment_id"] = str(shipment_id).strip()

        return enqueue_appointment_draft_send(tenant_slug=tenant_slug, payload=payload)


__all__ = (
    "AppointmentSchedulingSendConflictError",
    "AppointmentSchedulingSendService",
)
