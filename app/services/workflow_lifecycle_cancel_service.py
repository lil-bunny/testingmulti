"""Shared workflow lifecycle cancellation use case."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep
from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db
from app.domain.workflow_cancellation import WorkflowCancellationPolicy
from app.domain.workflow_cancellation_guards import (
    is_workflow_cancelled,
    is_workflow_cancellable,
    is_workflow_success_terminal,
)
from app.models.activity_type import ActivityType
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.activity_log_service import ActivityLogService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)


@dataclass(frozen=True)
class WorkflowCancelResult:
    cancelled: bool
    lifecycle_id: str | None = None
    skip_reason: str | None = None


class WorkflowLifecycleCancelService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        activity_service: ActivityLogService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._activity = activity_service or ActivityLogService()

    def cancel_by_shipment(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        policy: WorkflowCancellationPolicy,
        description: str,
        metadata: dict[str, Any],
    ) -> WorkflowCancelResult:
        tenant_uuid = resolve_graph_tenant_to_uuid((tenant_id or "").strip())
        if not tenant_uuid:
            return WorkflowCancelResult(cancelled=False, skip_reason="invalid_tenant")

        lifecycle_id = self._lifecycle.find_in_progress_lifecycle_id(
            tenant_id=tenant_id,
            policy=policy,
            shipment_id=shipment_row_id,
        )
        if not lifecycle_id:
            return WorkflowCancelResult(cancelled=False, skip_reason="not_found")

        row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id)
        from_status = status_type_from_db(row.get("status")) if row else None
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else None

        if is_workflow_cancelled(from_status, from_sub):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="already_cancelled",
            )

        if is_workflow_success_terminal(from_sub, policy):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="success_terminal",
            )

        if not is_workflow_cancellable(from_status, from_sub, policy):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="not_cancellable",
            )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_uuid,
                workflow_lifecycle_id=lifecycle_id,
                workflow_run_id=None,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=description,
                        metadata=dict(metadata),
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=policy.cancel_to_status,
                        to_sub_status=policy.cancel_to_sub_status,
                        metadata=dict(metadata),
                    ),
                ),
            )
        )

        logger.info(
            "workflow lifecycle cancelled workflow=%s lifecycle_id=%s tenant=%s",
            policy.workflow_name,
            lifecycle_id,
            tenant_id,
        )
        return WorkflowCancelResult(
            cancelled=True,
            lifecycle_id=lifecycle_id,
        )

    def supersede_by_shipment(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        policy: WorkflowCancellationPolicy,
        description: str,
        metadata: dict[str, Any],
    ) -> WorkflowCancelResult:
        tenant_uuid = resolve_graph_tenant_to_uuid((tenant_id or "").strip())
        if not tenant_uuid:
            return WorkflowCancelResult(cancelled=False, skip_reason="invalid_tenant")

        lifecycle_id = self._lifecycle.find_latest_non_cancelled_lifecycle_id(
            tenant_id=tenant_id,
            policy=policy,
            shipment_id=shipment_row_id,
        )
        if not lifecycle_id:
            return WorkflowCancelResult(cancelled=False, skip_reason="not_found")

        row = self._lifecycle.read_lifecycle_row_by_id(lifecycle_id)
        from_status = status_type_from_db(row.get("status")) if row else None
        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else None

        if is_workflow_cancelled(from_status, from_sub):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="already_cancelled",
            )

        if is_workflow_success_terminal(from_sub, policy):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="success_terminal",
            )

        if not is_workflow_cancellable(from_status, from_sub, policy):
            return WorkflowCancelResult(
                cancelled=False,
                lifecycle_id=lifecycle_id,
                skip_reason="not_cancellable",
            )

        self._activity.record_sequence(
            ActivityLogSequence(
                tenant_id=tenant_uuid,
                workflow_lifecycle_id=lifecycle_id,
                workflow_run_id=None,
                steps=(
                    ActivityLogStep(
                        activity_type=ActivityType.ACTION,
                        description=description,
                        metadata=dict(metadata),
                    ),
                    ActivityLogStep(
                        activity_type=ActivityType.STATUS_CHANGE,
                        to_status=policy.cancel_to_status,
                        to_sub_status=policy.cancel_to_sub_status,
                        metadata=dict(metadata),
                    ),
                ),
            )
        )

        logger.info(
            "workflow lifecycle superseded workflow=%s lifecycle_id=%s tenant=%s",
            policy.workflow_name,
            lifecycle_id,
            tenant_id,
        )
        return WorkflowCancelResult(
            cancelled=True,
            lifecycle_id=lifecycle_id,
        )
