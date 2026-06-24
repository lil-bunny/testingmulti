"""In-graph eligibility gates (layer 3)."""

from __future__ import annotations

from typing import Any

from app.domain.driver_assignment.escalation import skip_sub_statuses_from_driver_assignment_settings
from app.domain.driver_assignment.guards import (
    blocks_driver_assignment_escalation,
    blocks_driver_assignment_reminder,
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

        if wl_id:

            row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

            if blocks_driver_assignment_reminder(row):

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

        if lifecycle_id:

            row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id)

            current_step = self._reminder_step_from_lifecycle_row(row)

            raw_step = payload.get("reminder_step")

            try:

                requested_step = int(raw_step) if raw_step is not None else None

            except (TypeError, ValueError):

                requested_step = None

            if requested_step is not None and requested_step <= current_step:

                return EligibilityResult(skip_reason="reminder_step_already_sent")

        return EligibilityResult(skip_reason=None)

    def check_escalation_eligibility(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

        ) -> EligibilityResult:

        """Escalation_due gate: Turvo + lifecycle; no carrier thread required."""

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

            tenant_settings = payload.get("tenant_settings")

            skip_subs = skip_sub_statuses_from_driver_assignment_settings(

                tenant_settings if isinstance(tenant_settings, dict) else None

            )

            skip = delayed_workflow_step_skip_reason(row, skip_sub_statuses=skip_subs)

            if skip:

                return EligibilityResult(skip_reason=skip)

        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        if not wl_id and shipments_row_id and self._blocks_restart_for_shipment(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

        ):

            return EligibilityResult(skip_reason="already_completed")

        return EligibilityResult(skip_reason=None)

    @staticmethod
    def _reminder_step_from_lifecycle_row(row: dict[str, Any] | None) -> int:

        if not row:

            return 0

        sub = sub_status_type_from_db(row.get("sub_status"))

        mapping = {

            StatusSubType.REMINDER_1_SENT: 1,

            StatusSubType.REMINDER_2_SENT: 2,

            StatusSubType.REMINDER_3_SENT: 3,

            StatusSubType.REMINDER_4_SENT: 4,

        }

        return mapping.get(sub, 0)
