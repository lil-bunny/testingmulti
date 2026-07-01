"""Cancel active driver_assignment lifecycles from a workflow cancel trigger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.configs.workflow_cancellation_policies import (
    DRIVER_ASSIGNMENT_CANCEL_POLICY,
    DRIVER_ASSIGNMENT_RATECON_SUPERSEDE_POLICY,
)
from app.core.logger import get_logger
from app.domain.driver_assignment.activity_log_descriptions import (
    format_driver_assignment_cancelled_ratecon_superseded_action,
    format_driver_assignment_cancelled_tendered_action,
)
from app.domain.workflow_cancel_trigger import (
    RATECON_SUPERSEDED_TRIGGER,
    WorkflowCancelTrigger,
)
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_cancel_service import (
    WorkflowCancelResult,
    WorkflowLifecycleCancelService,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class WorkflowCancelAdapterResult:
    cancelled: bool
    lifecycle_id: str | None = None
    skip_reason: str | None = None

    @classmethod
    def from_workflow_result(cls, result: WorkflowCancelResult) -> WorkflowCancelAdapterResult:
        skip = result.skip_reason
        if skip == "not_found":
            skip = "no_active_lifecycle"
        return cls(
            cancelled=result.cancelled,
            lifecycle_id=result.lifecycle_id,
            skip_reason=skip,
        )


# ponytail: alias for tests/callers during rename
TenderedCancelResult = WorkflowCancelAdapterResult


class DriverAssignmentCancelService:
    def __init__(
        self,
        *,
        cancel_service: WorkflowLifecycleCancelService | None = None,
        shipments_service: ShipmentsService | None = None,
    ) -> None:
        self._cancel = cancel_service or WorkflowLifecycleCancelService()
        self._shipments = shipments_service or ShipmentsService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def cancel_for_trigger(
        self,
        trigger: WorkflowCancelTrigger,
    ) -> WorkflowCancelAdapterResult:
        correlation_error = trigger.shipment_correlation_error()
        if correlation_error:
            return WorkflowCancelAdapterResult(
                cancelled=False,
                skip_reason=correlation_error,
            )

        tenant_uuid = resolve_graph_tenant_to_uuid(self._clean(trigger.tenant_id))
        if not tenant_uuid:
            return WorkflowCancelAdapterResult(
                cancelled=False,
                skip_reason="invalid_tenant",
            )

        shipments_row_id = self._clean(trigger.shipments_row_id)
        shipment_number = self._clean(trigger.shipment_number)

        if not shipments_row_id and shipment_number:
            ship_row = self._shipments.get_by_shipment_number(
                tenant_id=tenant_uuid,
                shipment_number=shipment_number,
            )
            if not ship_row:
                return WorkflowCancelAdapterResult(
                    cancelled=False,
                    skip_reason="shipment_not_found",
                )
            shipments_row_id = self._clean(ship_row.get("id"))
            if not shipments_row_id:
                return WorkflowCancelAdapterResult(
                    cancelled=False,
                    skip_reason="shipment_not_found",
                )

        if trigger.trigger == RATECON_SUPERSEDED_TRIGGER:
            result = self._cancel.supersede_by_shipment(
                tenant_id=trigger.tenant_id,
                shipment_row_id=shipments_row_id,
                policy=DRIVER_ASSIGNMENT_RATECON_SUPERSEDE_POLICY,
                description=format_driver_assignment_cancelled_ratecon_superseded_action(),
                metadata={},
            )
            if result.cancelled:
                self._shipments.clear_driver_details(
                    tenant_id=tenant_uuid,
                    shipment_row_id=shipments_row_id,
                )
                logger.info(
                    "driver_assignment supersede lifecycle_id=%s tenant=%s shipment=%s",
                    result.lifecycle_id,
                    trigger.tenant_slug,
                    shipment_number,
                )
            elif result.skip_reason == "not_found":
                logger.info(
                    "driver_assignment supersede no-op tenant=%s shipment=%s load_id=%s",
                    trigger.tenant_slug,
                    shipment_number,
                    trigger.load_id,
                )
            return WorkflowCancelAdapterResult.from_workflow_result(result)

        result = self._cancel.cancel_by_shipment(
            tenant_id=trigger.tenant_id,
            shipment_row_id=shipments_row_id,
            policy=DRIVER_ASSIGNMENT_CANCEL_POLICY,
            description=format_driver_assignment_cancelled_tendered_action(),
            metadata={},
        )
        if not result.cancelled and result.skip_reason == "not_found":
            logger.info(
                "driver_assignment cancel no-op tenant=%s shipment=%s load_id=%s",
                trigger.tenant_slug,
                shipment_number,
                trigger.load_id,
            )
        elif result.cancelled:
            logger.info(
                "driver_assignment cancel lifecycle_id=%s tenant=%s shipment=%s",
                result.lifecycle_id,
                trigger.tenant_slug,
                shipment_number,
            )
        return WorkflowCancelAdapterResult.from_workflow_result(result)
