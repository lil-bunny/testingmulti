"""In-graph eligibility gates (layer 3)."""

from __future__ import annotations

from typing import Any

from app.domain.driver_assignment.guards import driver_assignment_reminder_skip_sub_statuses
from app.domain.driver_assignment.guards import (
    blocks_driver_assignment_escalation,
    blocks_driver_assignment_reminder,
)
from app.domain.driver_assignment.reminder_ladder import (
    MAX_SEQUENTIAL_REMINDER_STEP,
    schedule_reminder_step_from_payload,
    sent_schedule_steps_from_metadata,
    sequential_reminder_step_from_sub_status,
)
from app.domain.status_parsing import sub_status_type_from_db
from app.integrations.turvo.shipments import driver_assigned_from_payload
from app.models.status import StatusSubType
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    EligibilityResult,
)
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason

class IngressEligibilityMixin:
    def check_start_eligibility(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        exclude_run_id: str | None = None,

        ) -> EligibilityResult:

        """Layer 3: idempotent in-graph gate before scheduling reminders."""

        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            eligibility_skip = self._driver_request_skip_reason(shipment)

            if eligibility_skip:

                return EligibilityResult(skip_reason=eligibility_skip)

        skip_reason = self._evaluate_start_gates(

            tenant_id=tenant_id,

            tenant_settings=tenant_settings,

            payload=payload,

            require_process_enabled=False,

            exclude_run_id=exclude_run_id,

        )

        return EligibilityResult(skip_reason=skip_reason)

    def check_reminder_eligibility(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

        ) -> EligibilityResult:

        """Reminder_due gate: Turvo + driver-not-assigned only (no ratecon duplicate check)."""

        self._activity.record_delayed_shipment_fetch_timeout(payload)

        for key in ("thread_id", "load_id", "shipment_id", "shipments_row_id"):

            if not self._clean(payload.get(key)):

                return EligibilityResult(skip_reason="missing_correlation_keys")

        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            if driver_assigned_from_payload(shipment):

                return EligibilityResult(skip_reason="driver_already_assigned")

            eligibility_skip = self._driver_request_skip_reason(shipment)

            if eligibility_skip:

                return EligibilityResult(skip_reason=eligibility_skip)

        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        wl_id = self._clean(payload.get("workflow_lifecycle_id"))

        row_for_gate: dict[str, Any] | None = None

        if wl_id:

            row_for_gate = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

            if blocks_driver_assignment_reminder(row_for_gate):

                return EligibilityResult(skip_reason="already_completed")

        elif shipments_row_id and self._blocks_restart_for_shipment(
            tenant_id=tenant_id,
            shipments_row_id=shipments_row_id,
        ):

            return EligibilityResult(skip_reason="already_completed")

        lifecycle = self._lifecycle_service.check_lifecycle_exists(

            tenant_id=tenant_id,

            workflow_name=DRIVER_ASSIGNMENT_WORKFLOW,

            shipment_id=shipments_row_id,

        ) if shipments_row_id else {}

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id")) if lifecycle else None

        gate_wl_id = wl_id or lifecycle_id

        if gate_wl_id:

            row = (
                row_for_gate
                if gate_wl_id == wl_id and row_for_gate is not None
                else self._lifecycle_service.read_lifecycle_row_by_id(gate_wl_id)
            )

            current_seq = sequential_reminder_step_from_sub_status(
                (row or {}).get("sub_status")
            )

            if current_seq >= MAX_SEQUENTIAL_REMINDER_STEP:

                return EligibilityResult(skip_reason="reminder_cap_reached")

            schedule_step = schedule_reminder_step_from_payload(payload)

            if schedule_step is not None and schedule_step in sent_schedule_steps_from_metadata(
                (row or {}).get("metadata")
            ):

                return EligibilityResult(skip_reason="reminder_step_already_sent")

        return EligibilityResult(skip_reason=None)

    def check_escalation_eligibility(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

        ) -> EligibilityResult:

        """Escalation_due gate: Turvo + lifecycle; no carrier thread required."""

        self._activity.record_delayed_shipment_fetch_timeout(payload)

        for key in ("load_id", "shipment_id", "shipments_row_id", "workflow_lifecycle_id"):

            if not self._clean(payload.get(key)):

                return EligibilityResult(skip_reason="missing_correlation_keys")

        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            if driver_assigned_from_payload(shipment):

                return EligibilityResult(skip_reason="driver_already_assigned")

            eligibility_skip = self._driver_request_skip_reason(shipment)

            if eligibility_skip:

                return EligibilityResult(skip_reason=eligibility_skip)

        wl_id = self._clean(payload.get("workflow_lifecycle_id"))

        if wl_id:

            row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

            if blocks_driver_assignment_escalation(row):

                sub = sub_status_type_from_db((row or {}).get("sub_status"))

                if sub == StatusSubType.ESCALATED:

                    return EligibilityResult(skip_reason="already_escalated")

                return EligibilityResult(skip_reason="already_completed")

            skip = delayed_workflow_step_skip_reason(
                row,
                skip_sub_statuses=driver_assignment_reminder_skip_sub_statuses(),
            )

            if skip:

                return EligibilityResult(skip_reason=skip)

        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        if not wl_id and shipments_row_id and self._blocks_restart_for_shipment(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

        ):

            return EligibilityResult(skip_reason="already_completed")

        return EligibilityResult(skip_reason=None)
