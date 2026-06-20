"""Cancel active ratecon lifecycles superseded by a new inbound ratecon email."""

from __future__ import annotations

from typing import Any

from app.configs.workflow_cancellation_policies import RATECON_SUPERSEDE_POLICY
from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_ratecon_superseded_action
from app.domain.workflow_cancel_trigger import WorkflowCancelTrigger
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.driver_assignment_cancel_service import WorkflowCancelAdapterResult
from app.services.workflow_lifecycle_cancel_service import (
    WorkflowCancelResult,
    WorkflowLifecycleCancelService,
)

logger = get_logger(__name__)


class RateconCancelService:
    def __init__(
        self,
        *,
        cancel_service: WorkflowLifecycleCancelService | None = None,
    ) -> None:
        self._cancel = cancel_service or WorkflowLifecycleCancelService()

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
        if not shipments_row_id:
            return WorkflowCancelAdapterResult(
                cancelled=False,
                skip_reason="missing_shipment_correlation",
            )

        meta: dict[str, Any] = dict(trigger.metadata)
        if trigger.load_id:
            meta.setdefault("load_id", trigger.load_id)
        if trigger.shipment_number:
            meta.setdefault("shipment_id", trigger.shipment_number)

        result = self._cancel.supersede_by_shipment(
            tenant_id=trigger.tenant_id,
            shipment_row_id=shipments_row_id,
            policy=RATECON_SUPERSEDE_POLICY,
            description=format_ratecon_superseded_action(),
            metadata=meta,
        )
        if not result.cancelled and result.skip_reason == "not_found":
            logger.info(
                "ratecon supersede no-op tenant=%s shipment_row=%s load_id=%s",
                trigger.tenant_slug,
                shipments_row_id,
                trigger.load_id,
            )
        elif result.cancelled:
            logger.info(
                "ratecon supersede lifecycle_id=%s tenant=%s shipment_row=%s",
                result.lifecycle_id,
                trigger.tenant_slug,
                shipments_row_id,
            )
        return WorkflowCancelAdapterResult.from_workflow_result(result)
