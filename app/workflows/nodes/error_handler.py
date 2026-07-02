"""Global workflow failure sink node."""

from __future__ import annotations

import dataclasses
import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.error_catalog import ErrorCategory
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


def _failure_communication_id(workflow_error: dict[str, Any]) -> str | None:
    """Comm for the exception row: only when explicitly set on the error payload."""
    raw = workflow_error.get("communication_id")
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return str(uuid.UUID(s))
    except (ValueError, AttributeError):
        return None


def record_workflow_failure_node(state: WorkflowState) -> WorkflowState:
    """
    Global sink for catalog workflow errors.

    Writes ``exception`` + ``pending_review``, then enqueues alerts with the exception
    activity log id so outbound comms link to that row instead of a new ``action``.

    ``communication_id`` on the exception row comes only from ``error.communication_id``
    (explicit opt-in). Ambient ``state.data["communication_id"]`` is ignored so stale
    comms from earlier steps (tender send, reminders, etc.) are not linked.
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
        shipment_id = resolve_shipment_id(state.data)
        if shipment_id:
            metadata["shipment_id"] = shipment_id
        load_id = str(state.data.get("load_id") or "").strip()
        if load_id:
            metadata["load_id"] = load_id

        pause_type = PauseType.from_error_category(workflow_error.get("category"))
        # Business gaps are audited in activity logs, not via lifecycle pause.
        if (
            workflow_error.get("category") == ErrorCategory.BUSINESS.value
            or pause_type is PauseType.BUSINESS_EXCEPTION
        ):
            pause_type = None
            # DO NOT remove this: keeping it for upcoming usecases
            # pause_type = PauseType.BUSINESS_EXCEPTION

        failure_comm_id = _failure_communication_id(workflow_error)

        exception_cmd = LifecycleTransitionCommand.from_workflow_state(
            state,
            activity_type=ActivityType.EXCEPTION,
            actor_type=ActorType.SYSTEM,
            metadata=metadata or None,
            description=workflow_error.get("message"),
            update_lifecycle=False,
            pause_type=pause_type,
        )
        exception_cmd = dataclasses.replace(
            exception_cmd, communication_id=failure_comm_id
        )

        status_cmd = LifecycleTransitionCommand.from_workflow_state(
            state,
            activity_type=ActivityType.STATUS_CHANGE,
            to_status=StatusType.PENDING_REVIEW,
            actor_type=ActorType.SYSTEM,
        )
        status_cmd = dataclasses.replace(status_cmd, communication_id=None)

        try:
            transition_result = lifecycle_transition_service.apply_sequence(
                exception_cmd,
                status_cmd,
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

 