"""Appointment scheduling lifecycle persistence (DB via WorkflowLifecycleService only)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.metadata_keys import (
    APPOINTMENT_DRAFT_OUTBOUND_COMMUNICATION_ID,
    APPOINTMENT_DRAFT_OUTBOUND_SENT,
    EMAIL_DRAFT,
    LLM_SCHEDULING_DECISION,
    SCHEDULING_PAYLOAD,
)
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
        llm_scheduling_decision: dict[str, Any] | None = None,
    ) -> None:
        self._activity.record_draft_ready(
            state,
            email_draft=email_draft,
            scheduling_payload=scheduling_payload,
        )
        decision = llm_scheduling_decision if isinstance(llm_scheduling_decision, dict) else {}
        patch = {
            EMAIL_DRAFT: email_draft,
            SCHEDULING_PAYLOAD: scheduling_payload,
            LLM_SCHEDULING_DECISION: decision,
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

    def hydrate_confirm_context(self, state) -> None:
        """Load persisted draft/decision metadata into state for confirm branch."""
        lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        if not lifecycle_id:
            return
        row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        if isinstance(meta.get(EMAIL_DRAFT), dict):
            state.data["email_draft"] = meta[EMAIL_DRAFT]
            state.data.setdefault("workflow_lifecycle_metadata", meta)
        if isinstance(meta.get(SCHEDULING_PAYLOAD), dict):
            state.data["scheduling_payload"] = meta[SCHEDULING_PAYLOAD]
        if isinstance(meta.get(LLM_SCHEDULING_DECISION), dict):
            state.data["llm_scheduling_decision"] = meta[LLM_SCHEDULING_DECISION]
        scheduling = meta.get(SCHEDULING_PAYLOAD) if isinstance(meta.get(SCHEDULING_PAYLOAD), dict) else {}
        reference = str(
            state.data.get("reference_number")
            or scheduling.get("reference_number")
            or ""
        ).strip()
        if reference:
            state.data["reference_number"] = reference

        self._hydrate_turvo_shipment_id(state, lifecycle_id=lifecycle_id, lifecycle_row=row)

    def _hydrate_turvo_shipment_id(
        self,
        state,
        *,
        lifecycle_id: str,
        lifecycle_row: dict[str, Any],
    ) -> None:
        """Map portal ``shipments.id`` to Turvo ``shipment_number`` for confirm TMS writes."""
        tenant_id = str(
            getattr(state, "tenant_id", None)
            or state.data.get("tenant_id")
            or lifecycle_row.get("tenant_id")
            or ""
        ).strip()
        shipments_row_id = str(state.data.get("shipments_row_id") or "").strip()
        if not shipments_row_id:
            correlation = self._lifecycle.read_correlation_by_id(lifecycle_id) or {}
            shipments_row_id = str(correlation.get("shipment_id") or "").strip()
        if not shipments_row_id:
            shipments_row_id = str(state.data.get("shipment_id") or "").strip()
        if not tenant_id or not shipments_row_id:
            return

        state.data["shipments_row_id"] = shipments_row_id
        shipment_row = self._shipments.get_by_id(
            tenant_id=tenant_id,
            shipment_id=shipments_row_id,
        )
        if not shipment_row:
            return
        turvo_shipment_id = str(shipment_row.get("shipment_number") or "").strip()
        if turvo_shipment_id:
            state.data["shipment_id"] = turvo_shipment_id

    def draft_outbound_communication_id(self, lifecycle_id: str) -> str | None:
        row = self.load_context(lifecycle_id) or {}
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if not isinstance(meta, dict):
            return None
        comm_id = str(meta.get(APPOINTMENT_DRAFT_OUTBOUND_COMMUNICATION_ID) or "").strip()
        return comm_id or None

    def mark_draft_outbound_sent(
        self,
        lifecycle_id: str,
        *,
        communication_id: str,
    ) -> None:
        comm_id = str(communication_id or "").strip()
        patch: dict[str, Any] = {APPOINTMENT_DRAFT_OUTBOUND_SENT: True}
        if comm_id:
            patch[APPOINTMENT_DRAFT_OUTBOUND_COMMUNICATION_ID] = comm_id
        self._lifecycle.patch_metadata(
            lifecycle_id=lifecycle_id,
            metadata_patch=patch,
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

    def mark_completed(
        self,
        lifecycle_id: str,
        *,
        confirmed_delivery_at: str | None = None,
    ) -> None:
        patch: dict[str, Any] = {}
        if confirmed_delivery_at:
            patch["confirmed_delivery_at"] = confirmed_delivery_at
        if patch:
            self._lifecycle.patch_metadata(
                lifecycle_id=lifecycle_id,
                metadata_patch=patch,
            )
