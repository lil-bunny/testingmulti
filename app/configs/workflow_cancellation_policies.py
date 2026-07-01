"""Per-workflow cancellation policies and trigger registry."""

from __future__ import annotations

from app.domain.workflow_cancellation import WorkflowCancellationPolicy
from app.domain.workflow_cancel_trigger import (
    RATECON_SUPERSEDED_TRIGGER,
    SHIPMENT_TENDERED_TRIGGER,
)
from app.models.status import StatusSubType, StatusType

DRIVER_ASSIGNMENT_CANCEL_POLICY = WorkflowCancellationPolicy(
    workflow_name="driver_assignment",
    cancellable_statuses=frozenset(
        {StatusType.PROCESSING, StatusType.PENDING_REVIEW}
    ),
    success_terminal_sub_statuses=frozenset(
        {StatusSubType.UPLOADED_TO_TMS}
    ),
)

DRIVER_ASSIGNMENT_RATECON_SUPERSEDE_POLICY = WorkflowCancellationPolicy(
    workflow_name="driver_assignment",
    cancellable_statuses=frozenset(
        {
            StatusType.PROCESSING,
            StatusType.PENDING_REVIEW,
            StatusType.COMPLETED,
        }
    ),
    success_terminal_sub_statuses=frozenset(),
)

RATECON_SUPERSEDE_POLICY = WorkflowCancellationPolicy(
    workflow_name="ratecon",
    cancellable_statuses=frozenset(
        {
            StatusType.PROCESSING,
            StatusType.PENDING_REVIEW,
            StatusType.COMPLETED,
            StatusType.FAILED,
        }
    ),
    success_terminal_sub_statuses=frozenset(),
)

POD_LIFECYCLE_CANCEL_POLICY = WorkflowCancellationPolicy(
    workflow_name="pod_lifecycle",
    cancellable_statuses=frozenset(
        {StatusType.PROCESSING, StatusType.PENDING_REVIEW}
    ),
    success_terminal_sub_statuses=frozenset(
        {
            StatusSubType.DOCUMENT_PROCESSED,
            StatusSubType.UPLOADED_TO_TMS,
        }
    ),
)

CANCEL_TRIGGER_POLICIES: dict[str, tuple[WorkflowCancellationPolicy, ...]] = {
    SHIPMENT_TENDERED_TRIGGER: (DRIVER_ASSIGNMENT_CANCEL_POLICY,),
    RATECON_SUPERSEDED_TRIGGER: (
        RATECON_SUPERSEDE_POLICY,
        DRIVER_ASSIGNMENT_CANCEL_POLICY,
    ),
}
