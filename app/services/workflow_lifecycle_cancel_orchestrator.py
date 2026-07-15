"""Fan-out workflow lifecycle cancellation for a vendor-neutral trigger."""

from __future__ import annotations

from typing import Any, Protocol, TYPE_CHECKING

from app.configs.workflow_cancellation_policies import CANCEL_TRIGGER_POLICIES
from app.core.logger import get_logger
from app.services.driver_assignment.cancel_service import (
    DriverAssignmentCancelService,
    WorkflowCancelAdapterResult,
)
from app.services.ratecon_cancel_service import RateconCancelService
from app.services.workflow_lifecycle_cancel_service import WorkflowCancelResult

if TYPE_CHECKING:
    from app.domain.workflow_cancel_trigger import WorkflowCancelTrigger

logger = get_logger(__name__)


class WorkflowCancelAdapter(Protocol):
    def cancel_for_trigger(
        self, trigger: WorkflowCancelTrigger
    ) -> WorkflowCancelAdapterResult: ...


_CANCEL_ADAPTERS: dict[str, WorkflowCancelAdapter] = {
    "driver_assignment": DriverAssignmentCancelService(),
    "ratecon": RateconCancelService(),
}


class WorkflowLifecycleCancelOrchestrator:
    def cancel_for_trigger(
        self,
        trigger: WorkflowCancelTrigger,
    ) -> dict[str, WorkflowCancelResult]:
        policies = CANCEL_TRIGGER_POLICIES.get(trigger.trigger)
        if policies is None:
            logger.warning(
                "workflow cancel unknown trigger=%s tenant=%s",
                trigger.trigger,
                trigger.tenant_id,
            )
            return {}

        results: dict[str, WorkflowCancelResult] = {}
        for policy in policies:
            adapter = _CANCEL_ADAPTERS.get(policy.workflow_name)
            if adapter is None:
                continue
            adapter_result = adapter.cancel_for_trigger(trigger)
            results[policy.workflow_name] = WorkflowCancelResult(
                cancelled=adapter_result.cancelled,
                lifecycle_id=adapter_result.lifecycle_id,
                skip_reason=adapter_result.skip_reason,
            )
        return results

    @staticmethod
    def primary_entry(
        results: dict[str, WorkflowCancelResult],
        *,
        primary_workflow: str = "driver_assignment",
    ) -> WorkflowCancelResult:
        return results.get(
            primary_workflow,
            WorkflowCancelResult(cancelled=False, skip_reason="not_found"),
        )

    @staticmethod
    def to_api_content(
        results: dict[str, WorkflowCancelResult],
        *,
        primary_workflow: str = "driver_assignment",
    ) -> dict[str, Any]:
        primary = WorkflowLifecycleCancelOrchestrator.primary_entry(
            results,
            primary_workflow=primary_workflow,
        )
        return {
            "cancelled": primary.cancelled,
            "lifecycle_id": primary.lifecycle_id,
            "skip_reason": primary.skip_reason,
            "workflows": {
                name: {
                    "cancelled": r.cancelled,
                    "lifecycle_id": r.lifecycle_id,
                    "skip_reason": r.skip_reason,
                }
                for name, r in results.items()
            },
        }
