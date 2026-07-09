"""Pre-send eligibility for ``pod_lifecycle`` ``reminder_due`` runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.pod_lifecycle.guards import pod_reminder_skip_sub_statuses
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.load_tendering_lifecycle_guards import delayed_workflow_step_skip_reason


@dataclass(frozen=True)
class PodReminderEligibilityResult:
    skip_reason: str | None = None

    @property
    def eligible(self) -> bool:
        return self.skip_reason is None


class PodLifecycleReminderEligibilityService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    def check(
        self,
        *,
        workflow_lifecycle_id: str | None,
        state_data: dict[str, Any],
    ) -> PodReminderEligibilityResult:
        wl_id = str(workflow_lifecycle_id or "").strip()
        if not wl_id:
            return PodReminderEligibilityResult(skip_reason="missing_workflow_lifecycle_id")

        row = self._lifecycle.read_lifecycle_row_by_id(wl_id)
        skip = delayed_workflow_step_skip_reason(
            row,
            skip_sub_statuses=pod_reminder_skip_sub_statuses(state_data),
        )
        return PodReminderEligibilityResult(skip_reason=skip)
