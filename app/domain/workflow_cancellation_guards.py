"""Pure guards for workflow lifecycle cancellation."""

from __future__ import annotations

from app.domain.workflow_cancellation import WorkflowCancellationPolicy
from app.models.status import StatusSubType, StatusType


def is_workflow_cancelled(
    status: StatusType | None,
    sub_status: StatusSubType | None,
) -> bool:
    return (
        status == StatusType.COMPLETED
        and sub_status == StatusSubType.CANCELLED
    )


def is_workflow_success_terminal(
    sub_status: StatusSubType | None,
    policy: WorkflowCancellationPolicy,
) -> bool:
    return sub_status in policy.success_terminal_sub_statuses


def is_workflow_cancellable(
    status: StatusType | None,
    sub_status: StatusSubType | None,
    policy: WorkflowCancellationPolicy,
) -> bool:
    if is_workflow_cancelled(status, sub_status):
        return False
    if is_workflow_success_terminal(sub_status, policy):
        return False
    return status in policy.cancellable_statuses


def workflow_ingress_terminal_sub_statuses(
    policy: WorkflowCancellationPolicy,
) -> frozenset[StatusSubType]:
    return policy.success_terminal_sub_statuses | frozenset({policy.cancel_to_sub_status})
