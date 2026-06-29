"""Node: resolve international Gelita tenders skipped from the domestic pipeline."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.activity_log_write import ActivityLogWrite
from app.domain.error_catalog import BusinessError
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusSubType, StatusType
from app.services.activity_log_service import ActivityLogService
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def resolve_international_delivery_skip(state):
    """Log international skip exception and mark lifecycle resolved manually."""
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()
    tender_id = str(state.data.get("tender_id") or "").strip()
    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not run_id:
        logger.warning(
            "resolve_international_delivery_skip skipped missing ids "
            "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",
            bool(wl_id),
            bool(tenant_id),
            bool(run_id),
        )
        return state

    metadata: dict[str, Any] = {"error": BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.value}
    if tender_id:
        metadata["tender_id"] = tender_id

    activity_log_service = ActivityLogService()
    activity_log_service.record_exception(
        ActivityLogWrite(
            tenant_id=tenant_id,
            workflow_lifecycle_id=wl_id,
            workflow_run_id=run_id,
            description=BusinessError.INTERNATIONAL_DELIVERY_SKIPPED.description,
            metadata=metadata,
            actor_type=ActorType.SYSTEM,
        )
    )

    lifecycle_transition_service = LifecycleTransitionService()
    lifecycle_transition_service.apply_from_state(
        state,
        activity_type=ActivityType.STATUS_CHANGE,
        to_status=StatusType.COMPLETED,
        to_sub_status=StatusSubType.RESOLVED_MANUALLY,
        actor_type=ActorType.SYSTEM,
        metadata=metadata,
    )
    return state
