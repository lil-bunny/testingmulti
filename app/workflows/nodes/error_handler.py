"""Global workflow failure sink node."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.state import WorkflowState
from app.models.activity_type import ActivityType, ActorType
from app.models.status import StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService

logger = get_logger(__name__)


def record_workflow_failure_node(state: WorkflowState) -> WorkflowState:
    """
    Global sink for workflow errors.
    Updates the lifecycle to FAILED and terminates the graph.
    """
    workflow_error = state.data.get("error")
    if not isinstance(workflow_error, dict):
        workflow_error = {}

    error_code = workflow_error.get("code")
    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()
    tenant_id = (state.tenant_id or "").strip()
    run_id = str(state.execution_id or "").strip()

    if wl_id and tenant_id and run_id:
        lifecycle_transition_service = LifecycleTransitionService()
        metadata: dict[str, Any] = {}
        if error_code:
            metadata["error"] = error_code
            if workflow_error.get("category"):
                metadata["error_category"] = workflow_error["category"]
            if workflow_error.get("message"):
                metadata["error_description"] = workflow_error["message"]
        if state.data.get("tender_id"):
            metadata["tender_id"] = state.data["tender_id"]
        if state.data.get("pack_code"):
            metadata["pack_code"] = state.data["pack_code"]

        try:
            lifecycle_transition_service.apply_from_state(
                state,
                to_status=StatusType.PENDING_REVIEW,
                activity_type=ActivityType.STATUS_CHANGE,
                actor_type=ActorType.SYSTEM,
                metadata=metadata or None,
            )
        except Exception:
            logger.exception(
                "record_workflow_failure_node failed tenant_id=%s run_id=%s error_code=%s",
                tenant_id,
                run_id,
                error_code,
            )

    return state
