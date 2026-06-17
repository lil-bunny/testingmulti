"""Global workflow failure sink node."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.lifecycle_transition import LifecycleTransitionCommand
from app.domain.state import WorkflowState
from app.workflows.shipment_resolver import resolve_shipment_id
from app.models.activity_type import ActivityType, ActorType
from app.models.pause_type import PauseType
from app.models.status import StatusType
from app.services.lifecycle_transition_service import LifecycleTransitionService
from app.services.workflow_error_alert_enqueue_service import (
    enqueue_workflow_error_alert_from_state,
)

logger = get_logger(__name__)


def record_workflow_failure_node(state: WorkflowState) -> WorkflowState:
    """
    Global sink for catalog workflow errors.

    Writes ``exception`` + ``pending_review``, then enqueues alerts with the exception
    activity log id so outbound comms link to that row instead of a new ``action``.
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
        if state.data.get("delivery_address_code"):
            metadata["delivery_address_code"] = state.data["delivery_address_code"]
        shipment_id = resolve_shipment_id(state.data)
        if shipment_id:
            metadata["shipment_id"] = shipment_id
        load_id = str(state.data.get("load_id") or "").strip()
        if load_id:
            metadata["load_id"] = load_id

        pause_type = PauseType.from_error_category(workflow_error.get("category"))

        try:
            transition_result = lifecycle_transition_service.apply_sequence(
                LifecycleTransitionCommand.from_workflow_state(
                    state,
                    activity_type=ActivityType.EXCEPTION,
                    actor_type=ActorType.SYSTEM,
                    metadata=metadata or None,
                    description=workflow_error.get("message"),
                    update_lifecycle=False,
                    pause_type=pause_type,
                ),
                LifecycleTransitionCommand.from_workflow_state(
                    state,
                    activity_type=ActivityType.STATUS_CHANGE,
                    to_status=StatusType.PENDING_REVIEW,
                    actor_type=ActorType.SYSTEM,
                ),
            )
        except Exception:
            logger.exception(
                "record_workflow_failure_node failed tenant_id=%s run_id=%s error_code=%s",
                tenant_id,
                run_id,
                error_code,
            )
        else:
            exception_activity_log_id = (
                transition_result.activity_log_ids[0]
                if transition_result.activity_log_ids
                else None
            )
            enqueue_workflow_error_alert_from_state(
                state,
                exception_activity_log_id=exception_activity_log_id,
            )

    return state
