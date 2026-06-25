"""Shared workflow lifecycle cancellation policy (pure, no I/O)."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.status import StatusSubType, StatusType


@dataclass(frozen=True)
class WorkflowCancellationPolicy:
    workflow_name: str
    cancellable_statuses: frozenset[StatusType]
    success_terminal_sub_statuses: frozenset[StatusSubType]
    cancel_to_status: StatusType = StatusType.COMPLETED
    cancel_to_sub_status: StatusSubType = StatusSubType.CANCELLED

    def in_progress_status_values(self) -> tuple[str, ...]:
        return tuple(s.value for s in self.cancellable_statuses)

    def excluded_sub_status_values(self) -> tuple[str, ...]:
        excluded = set(self.success_terminal_sub_statuses)
        excluded.add(self.cancel_to_sub_status)
        return tuple(s.value for s in excluded)
