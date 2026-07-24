"""Appointment scheduling lifecycle persistence (DB via WorkflowLifecycleService only)."""

from __future__ import annotations

from typing import Any

from app.domain.appointment_scheduling.failure import SchedulingFailure
from app.domain.appointment_scheduling.skip_reasons import scheduling_failure_from_skip
from app.domain.error_catalog import SystemError
from app.domain.appointment_scheduling.constants import (
    EMAIL_DRAFT,
    LLM_APPOINTMENT_DECISION,
    APPOINTMENT_FAILURE_REASON,
    COSTCO_PROPOSED_DELIVERY_WALL_TIME,
)
from app.domain.appointment_scheduling.metadata_hydration import (
    apply_lifecycle_email_draft_to_state,
    apply_lifecycle_appointment_decision_to_state,
    hydrate_shipment_facts_into_state,
)
from app.domain.appointment_scheduling.state_hygiene import strip_intake_checkpoint_data
from app.domain.appointment_scheduling.utils import is_costco_customer
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.activity_service import (
    ActivityService,
)
from app.services.appointment_scheduling.teams_notification_service import (
    TeamsNotificationService,
)
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.appointment_scheduling.po_number import resolve_scheduling_po_number


class LifecycleService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        activity_service: ActivityService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._activity = activity_service or ActivityService(
            lifecycle_service=self._lifecycle,
        )
        self._shipments = shipments_service or ShipmentsService()

    def load_context(self, lifecycle_id: str) -> dict[str, Any] | None:
        return self._lifecycle.read_lifecycle_row_by_id(lifecycle_id)

    def hydrate_read_context(self, state) -> None:
        """Load slim lifecycle fields for send/reply routing (no full row on state).

        ``email_draft`` (incl. full HTML) is only hydrated for ``appointment_draft_send``.
        Reply runs need status/sub-status only — draft stays in lifecycle metadata.
        """
        lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        if not lifecycle_id:
            return
        row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        state.data["workflow_lifecycle_status"] = str(row.get("status") or "").strip()
        state.data["workflow_lifecycle_sub_status"] = str(row.get("sub_status") or "").strip()

        event_type = str(state.data.get("event_type") or "").strip()
        if event_type == WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value:
            # Reply classification / TMS / confirmation do not use draft HTML.
            state.data.pop(EMAIL_DRAFT, None)
            return

        if event_type == WorkflowRunEventType.APPOINTMENT_DRAFT_SEND.value:
            meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            if isinstance(meta, dict):
                apply_lifecycle_email_draft_to_state(state, meta)

    def strip_intake_checkpoint(self, state) -> None:
        strip_intake_checkpoint_data(state.data)

    def persist_draft_ready(
        self,
        state,
        *,
        lifecycle_id: str,
        email_draft: dict[str, Any],
        appointment_payload: dict[str, Any],
        llm_appointment_decision: dict[str, Any] | None = None,
    ) -> None:
        self._activity.record_draft_ready(
            state,
            email_draft=email_draft,
            appointment_payload=appointment_payload,
        )
        decision = llm_appointment_decision if isinstance(llm_appointment_decision, dict) else {}
        metadata_patch: dict[str, Any] = {EMAIL_DRAFT: email_draft}
        if decision:
            metadata_patch[LLM_APPOINTMENT_DECISION] = decision
        self._lifecycle.patch_metadata(
            lifecycle_id=lifecycle_id,
            metadata_patch=metadata_patch,
        )

        shipments_row_id = str(state.data.get("shipments_row_id") or "").strip()
        tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
        if shipments_row_id and tenant_id:
            customer_name = str(state.data.get("customer_name") or "").strip()
            pickup_time = str(decision.get("selected_pickup_time") or "").strip() or None
            delivery_time = (
                COSTCO_PROPOSED_DELIVERY_WALL_TIME
                if is_costco_customer(customer_name)
                else None
            )
            shipment_row = self._shipments.get_by_id(
                tenant_id=tenant_id,
                shipment_id=shipments_row_id,
            )
            pickup_tz = (
                str(shipment_row.get("pickup_timezone") or "").strip() or None
                if shipment_row
                else None
            )
            delivery_tz = (
                str(shipment_row.get("delivery_timezone") or "").strip() or None
                if shipment_row
                else None
            )
            self._shipments.update_proposed_appointments(
                tenant_id=tenant_id,
                shipment_row_id=shipments_row_id,
                proposed_pickup_at=appointment_payload.get("proposed_pickup_at"),
                proposed_delivery_at=appointment_payload.get("proposed_delivery_at"),
                proposed_pickup_time=pickup_time,
                proposed_delivery_time=delivery_time,
                pickup_timezone=pickup_tz,
                delivery_timezone=delivery_tz,
            )
            shipment_meta_patch = self._shipment_metadata_patch(
                state,
                appointment_payload=appointment_payload,
            )
            if shipment_meta_patch:
                self._shipments.merge_metadata(
                    tenant_id=tenant_id,
                    shipment_row_id=shipments_row_id,
                    metadata_patch=shipment_meta_patch,
                )

    @staticmethod
    def _shipment_metadata_patch(
        state,
        *,
        appointment_payload: dict[str, Any],
    ) -> dict[str, Any]:
        patch: dict[str, Any] = {}
        reference = str(appointment_payload.get("reference_number") or "").strip()
        if reference:
            patch["reference_number"] = reference
        load_id = str(state.data.get("load_id") or "").strip()
        if load_id:
            patch["load_id"] = load_id
        customer_name = str(state.data.get("customer_name") or "").strip()
        po = resolve_scheduling_po_number(
            customer_name=customer_name,
            turvo_payload=state.data.get("shipment")
            if isinstance(state.data.get("shipment"), dict)
            else None,
            pickup_dropoff=state.data.get("pickup_dropoff_data")
            if isinstance(state.data.get("pickup_dropoff_data"), dict)
            else None,
        )
        if po:
            patch["po_number"] = po
        pickup_dropoff = state.data.get("pickup_dropoff_data")
        if isinstance(pickup_dropoff, dict):
            pallet_raw = pickup_dropoff.get("pallet_count")
            if pallet_raw is not None:
                try:
                    patch["pallet_count"] = int(pallet_raw)
                except (TypeError, ValueError):
                    pass
        draft_static = state.data.get("draft_static")
        if isinstance(draft_static, dict):
            commodity = str(draft_static.get("commodity") or "").strip()
            if commodity:
                patch["commodity"] = commodity
        return patch

    def hydrate_appointment_send_context(self, state) -> None:
        """Load persisted draft and shipment facts into state for confirm branch."""
        lifecycle_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
        if not lifecycle_id:
            return
        row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id) or {}
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        if not isinstance(meta, dict):
            meta = {}
        apply_lifecycle_email_draft_to_state(state, meta)
        apply_lifecycle_appointment_decision_to_state(state, meta)
        self._hydrate_turvo_shipment_id(state, lifecycle_id=lifecycle_id, lifecycle_row=row)

        tenant_id = str(
            getattr(state, "tenant_id", None)
            or state.data.get("tenant_id")
            or row.get("tenant_id")
            or ""
        ).strip()
        shipments_row_id = str(state.data.get("shipments_row_id") or "").strip()
        if tenant_id and shipments_row_id:
            shipment_row = self._shipments.get_by_id(
                tenant_id=tenant_id,
                shipment_id=shipments_row_id,
            )
            if shipment_row:
                hydrate_shipment_facts_into_state(state, shipment_row=shipment_row)

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

    def mark_restartable_skip(
        self,
        lifecycle_id: str,
        skip_reason: str,
        *,
        tenant_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> None:
        """Mark lifecycle restartable after a pre-workflow skip (e.g. enqueue_failed)."""
        reason = str(skip_reason or "").strip()
        failure = scheduling_failure_from_skip(reason)
        if failure is None:
            failure = SchedulingFailure(
                code=reason or SystemError.UNEXPECTED_NODE_FAILURE.value,
                message=reason.replace("_", " ") if reason else "unexpected failure",
                category=SystemError.UNEXPECTED_NODE_FAILURE.category,
            )
        self.mark_failed(
            lifecycle_id,
            failure,
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
        )

    def mark_failed(
        self,
        lifecycle_id: str,
        failure: SchedulingFailure,
        *,
        tenant_id: str | None = None,
        workflow_run_id: str | None = None,
    ) -> None:
        if tenant_id and workflow_run_id:
            self._activity.record_failed(
                tenant_id=tenant_id,
                workflow_lifecycle_id=lifecycle_id,
                workflow_run_id=workflow_run_id,
                failure=failure,
            )
        self._lifecycle.patch_metadata(
            lifecycle_id=lifecycle_id,
            metadata_patch={APPOINTMENT_FAILURE_REASON: failure.code},
        )

    def finalize_after_teams_notify(self, state):
        """Teams notify + draft pending review transition + strip intake checkpoint.

        Teams outcome is not mirrored onto LangGraph state (write-only noise).
        """
        teams = TeamsNotificationService()
        result = teams.notify_from_state(state)
        self._activity.record_draft_pending_review(state)
        self.strip_intake_checkpoint(state)
        return result

    def finalize_appointment_awaiting_reply(self, state) -> None:
        actor_id = str(state.data.get("actor_user_id") or "").strip() or None
        communication_id = str(state.data.get("communication_id") or "").strip() or None
        self._activity.record_confirm_email_sent(
            state,
            communication_id=communication_id,
            actor_id=actor_id,
        )
        self._activity.record_awaiting_customer_reply(state)
