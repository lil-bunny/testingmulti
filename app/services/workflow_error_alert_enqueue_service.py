"""Enqueue async workflow error alert delivery from graph failure sink."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.workflow_error_alert_payload import WorkflowErrorAlertPayload
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.state import WorkflowState

logger = get_logger(__name__)


def enqueue_workflow_error_alert_from_state(
    state: WorkflowState,
    *,
    exception_activity_log_id: str | None = None,
) -> None:
    """
    Queue async alert delivery after a successful failure lifecycle transition.

    ``exception_activity_log_id`` is the ``exception`` row from the failure sink.
    Swallows broker errors so the graph failure sink always completes.
    """
    workflow_name = str(state.data.get("workflow_name") or "").strip()
    payload = WorkflowErrorAlertPayload.from_workflow_state_data(
        tenant_id=state.tenant_id,
        workflow_name=workflow_name,
        workflow_run_id=state.execution_id,
        data=state.data,
        exception_activity_log_id=exception_activity_log_id,
    )
    if payload is None:
        return

    try:
        from app.tasks.workflow_error_alerts import send_workflow_error_alert

        send_workflow_error_alert.apply_async(kwargs={"payload": payload.model_dump()})
        logger.info(
            "workflow_error_alert enqueued lifecycle_id=%s run_id=%s error_code=%s",
            payload.workflow_lifecycle_id,
            payload.workflow_run_id,
            payload.error.get("code"),
        )
    except Exception:
        logger.exception(
            "workflow_error_alert enqueue failed tenant_id=%s run_id=%s",
            state.tenant_id,
            state.execution_id,
        )
