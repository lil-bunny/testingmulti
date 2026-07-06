"""Shared gate helpers for driver assignment ingress."""

from __future__ import annotations

from typing import Any

from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.domain.tenant_settings.enabled_processes import enabled_processes_from_settings
from app.integrations.turvo.shipments import (
    driver_assigned_from_payload,
    driver_request_eligible_from_payload,
    pickup_appointment_from_payload,
)
from app.models.status import StatusSubType, StatusType
from app.services.driver_assignment.ingress_types import (
    DRIVER_ASSIGNMENT_WORKFLOW,
    LAYER1_ACTIVITY_SKIP_REASONS,
)

class IngressGatesMixin:
    @staticmethod
    def _clean(value: Any) -> str | None:

        if value is None:

            return None

        s = str(value).strip()

        return s if s else None

    @staticmethod
    def _is_process_enabled(tenant_settings: dict[str, Any] | None) -> bool:

        return DRIVER_ASSIGNMENT_WORKFLOW in enabled_processes_from_settings(

            tenant_settings

        )

    @staticmethod
    def _driver_request_skip_reason(turvo_payload: Any) -> str | None:

        if not isinstance(turvo_payload, dict):

            return "shipment_not_in_state"

        return driver_request_eligible_from_payload(turvo_payload)

    @staticmethod
    def _enrich_pickup_from_turvo_payload(

        turvo_payload: Any,

        *,

        ignore_driver_assigned: bool = False,

        ) -> tuple[str | None, dict[str, Any]]:

        if not isinstance(turvo_payload, dict):

            return "shipment_not_in_state", {}

        if not ignore_driver_assigned and driver_assigned_from_payload(turvo_payload):

            return "driver_already_assigned", {}

        pickup = pickup_appointment_from_payload(turvo_payload)

        if pickup is None:

            return "pickup_appointment_not_found", {}

        return None, {

            "pickup_appointment_at": pickup.at_utc.isoformat(),

            "pickup_appointment_timezone": pickup.timezone,

            "pickup_appointment_source": pickup.source,

            "shipment": turvo_payload,

        }

    @staticmethod
    def _ensure_pickup_on_payload(payload: dict[str, Any]) -> None:

        if IngressGatesMixin._clean(payload.get("pickup_appointment_at")):

            return

        shipment = payload.get("shipment")

        if isinstance(shipment, dict):

            pickup = pickup_appointment_from_payload(shipment)

            if pickup is not None:

                payload["pickup_appointment_at"] = pickup.at_utc.isoformat()

                payload["pickup_appointment_timezone"] = pickup.timezone

                payload["pickup_appointment_source"] = pickup.source

                return

        raise Exception("Missing pickup_appointment_at for 'driver_assignment'")

    def _blocks_restart_for_shipment(

        self,

        *,

        tenant_id: str,

        shipments_row_id: str,

        ) -> bool:

        active_id = self._lifecycle_service.find_active_driver_assignment_lifecycle_id(

            tenant_id=tenant_id,

            shipment_id=shipments_row_id,

        )

        if active_id:

            return True

        return self._lifecycle_service.has_success_terminal_driver_assignment_lifecycle(

            tenant_id=tenant_id,

            shipment_id=shipments_row_id,

        )

    def _ratecon_lifecycle_complete(self, ratecon_lifecycle_id: str) -> bool:

        row = self._lifecycle_service.read_lifecycle_row_by_id(ratecon_lifecycle_id)

        if not row:

            return False

        status = status_type_from_db(row.get("status"))

        return status == StatusType.COMPLETED

    def _is_duplicate_ratecon_completed(

        self,

        *,

        tenant_id: str,

        shipments_row_id: str,

        exclude_run_id: str | None = None,

        workflow_lifecycle_id: str | None = None,

        ) -> bool:

        return self._runs_service.is_ratecon_completed_blocked_for_shipment(

            tenant_id=tenant_id,

            workflow_lifecycle_id=workflow_lifecycle_id,

            shipment_id=shipments_row_id,

            exclude_run_id=exclude_run_id,

        )

    def _resolve_thread_id(

        self,

        *,

        tenant_id: str,

        payload: dict[str, Any],

        ) -> str | None:

        thread_id = self._clean(payload.get("thread_id"))

        if thread_id:

            return thread_id

        ratecon_lifecycle_id = self._clean(payload.get("ratecon_workflow_lifecycle_id"))

        if not ratecon_lifecycle_id:

            return None

        return self._communications.resolve_thread_for_lifecycle(

            tenant_id=tenant_id,

            workflow_lifecycle_id=ratecon_lifecycle_id,

        )

    def _evaluate_start_gates(

        self,

        *,

        tenant_id: str,

        tenant_settings: dict[str, Any] | None,

        payload: dict[str, Any],

        require_process_enabled: bool = True,

        exclude_run_id: str | None = None,

        ) -> str | None:

        if require_process_enabled and not self._is_process_enabled(tenant_settings):

            return "process_disabled"

        shipments_row_id = self._clean(payload.get("shipments_row_id"))

        load_id = self._clean(payload.get("load_id"))

        shipment_id = self._clean(payload.get("shipment_id"))

        ratecon_lifecycle_id = self._clean(

            payload.get("ratecon_workflow_lifecycle_id")

        )

        if not all((shipments_row_id, load_id, shipment_id, ratecon_lifecycle_id)):

            return "missing_correlation_keys"

        thread_id = self._resolve_thread_id(tenant_id=tenant_id, payload=payload)

        if not thread_id:

            return "missing_thread_id"

        ratecon_row = self._lifecycle_service.read_lifecycle_row_by_id(

            ratecon_lifecycle_id

        )

        if not ratecon_row:

            return "ratecon_lifecycle_not_found"

        if not self._ratecon_lifecycle_complete(ratecon_lifecycle_id):

            return "ratecon_not_complete"

        shipment_row = self._shipments.get_by_id(

            tenant_id=tenant_id,

            shipment_id=shipments_row_id,

        )

        if not shipment_row:

            return "shipment_not_found"

        if self._blocks_restart_for_shipment(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

        ):

            return "already_completed"

        if self._is_duplicate_ratecon_completed(

            tenant_id=tenant_id,

            shipments_row_id=shipments_row_id,

            exclude_run_id=exclude_run_id,

        ):

            return "duplicate_ratecon_completed"

        return None

    def _log_layer1_skip_on_ratecon(

        self,

        *,

        state,

        tenant_id: str,

        skip_reason: str,

        payload: dict[str, Any],

        pickup_fields: dict[str, Any] | None = None,

        ) -> None:

        if skip_reason not in LAYER1_ACTIVITY_SKIP_REASONS:

            return

        ratecon_wl = self._clean(

            state.data.get("workflow_lifecycle_id") if hasattr(state, "data") else None

        )

        run_id = self._clean(getattr(state, "execution_id", None))

        if not ratecon_wl or not tenant_id or not run_id:

            return

        pf = pickup_fields or {}

        self._activity.record_not_started_on_ratecon(

            tenant_id=tenant_id,

            ratecon_workflow_lifecycle_id=ratecon_wl,

            workflow_run_id=run_id,

            skip_reason=skip_reason,

            shipment_id=self._clean(payload.get("shipment_id")),

            load_id=self._clean(payload.get("load_id")),

            shipments_row_id=self._clean(payload.get("shipments_row_id")),

            pickup_appointment_at=self._clean(pf.get("pickup_appointment_at")),

            pickup_appointment_timezone=self._clean(pf.get("pickup_appointment_timezone")),

        )
