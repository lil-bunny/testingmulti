"""Appointment scheduling lifecycle persistence (DB via WorkflowLifecycleService only)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.metadata_keys import EMAIL_DRAFT, SCHEDULING_PAYLOAD
from app.services.appointment_scheduling.activity_service import (
    AppointmentSchedulingActivityService,
)
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService


class AppointmentSchedulingLifecycleService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        activity_service: AppointmentSchedulingActivityService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._activity = activity_service or AppointmentSchedulingActivityService(
            lifecycle_service=self._lifecycle,
        )
        self._shipments = shipments_service or ShipmentsService()

    def load_context(self, lifecycle_id: str) -> dict[str, Any] | None:
        return self._lifecycle.read_lifecycle_row_by_id(lifecycle_id)

    def persist_draft_ready(
        self,
        state,
        *,
        lifecycle_id: str,
        email_draft: dict[str, Any],
        scheduling_payload: dict[str, Any],
    ) -> None:
        self._activity.record_draft_ready(
            state,
            email_draft=email_draft,
            scheduling_payload=scheduling_payload,
        )
        patch = {
            EMAIL_DRAFT: email_draft,
            SCHEDULING_PAYLOAD: scheduling_payload,
        }
        self._lifecycle.patch_metadata(
            lifecycle_id=lifecycle_id,
            metadata_patch=patch,
        )

        shipments_row_id = str(state.data.get("shipments_row_id") or "").strip()
        tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
        if shipments_row_id and tenant_id:
            self._shipments.update_proposed_appointments(
                tenant_id=tenant_id,
                shipment_row_id=shipments_row_id,
                proposed_pickup_at=scheduling_payload.get("proposed_pickup_at"),
                proposed_delivery_at=scheduling_payload.get("proposed_delivery_at"),
            )

    def mark_failed(
        self,
        lifecycle_id: str,
        reason: str,
        *,
        tenant_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> None:
        if tenant_id and workflow_run_id:
            self._activity.record_failed(
                tenant_id=tenant_id,
                workflow_lifecycle_id=lifecycle_id,
                workflow_run_id=workflow_run_id,
                reason=reason,
            )
        self._lifecycle.patch_metadata(
            lifecycle_id=lifecycle_id,
            metadata_patch={"scheduling_failure_reason": reason},
        )
