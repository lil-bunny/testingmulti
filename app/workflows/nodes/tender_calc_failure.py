"""Record lifecycle failure when tender parameter calculation cannot continue."""

from __future__ import annotations

from typing import Any

from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService


def record_tender_calc_failure(state: Any, *, error_code: str) -> None:
    """
    Mark lifecycle ``failed`` and append a status_change activity log (status only).

    Call from ``calculate_tender_params`` when the run cannot continue.
    """
    wl_id = str(getattr(state, "data", {}).get("workflow_lifecycle_id") or "").strip()
    tenant_id = (getattr(state, "tenant_id", None) or "").strip()
    run_id = str(getattr(state, "execution_id", None) or "").strip()
    tender_id = str(getattr(state, "data", {}).get("tender_id") or "").strip()
    if not wl_id or not tenant_id or not run_id:
        return

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply(
        LifecycleTransitionCommand(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=StatusType.FAILED,
            actor_type=ActorType.SYSTEM
        )
    )
