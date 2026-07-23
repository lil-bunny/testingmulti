"""Workflow error alert enqueue uses work-queue routing + tenant_slug."""

from __future__ import annotations

from unittest.mock import patch

from app.core.config import settings
from app.domain.state import WorkflowState
from app.services.workflow_error_alert_enqueue_service import (
    enqueue_workflow_error_alert_from_state,
)


def test_enqueue_workflow_error_alert_routes_t3ra_queue() -> None:
    state = WorkflowState(
        tenant_id="tenant-uuid",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={
            "workflow_name": "pod_lifecycle",
            "workflow_lifecycle_id": "wl-1",
            "error": {"category": "system", "code": "x", "message": "boom"},
            "tenant_settings": {},
        },
    )
    with patch(
        "app.tasks.workflow_error_alerts.send_workflow_error_alert.apply_async"
    ) as mock_apply:
        enqueue_workflow_error_alert_from_state(state, exception_activity_log_id="act-1")

    mock_apply.assert_called_once()
    assert mock_apply.call_args.kwargs["queue"] == settings.T3RA_WORK_QUEUE
    payload = mock_apply.call_args.kwargs["kwargs"]["payload"]
    assert payload["tenant_slug"] == "t3ra"
    assert payload["tenant_id"] == "tenant-uuid"


def test_enqueue_workflow_error_alert_routes_gelita_default() -> None:
    state = WorkflowState(
        tenant_id="tenant-uuid",
        tenant_slug="gelita",
        execution_id="run-2",
        data={
            "workflow_name": "load_tendering",
            "workflow_lifecycle_id": "wl-2",
            "error": {"category": "system", "code": "y", "message": "fail"},
            "tenant_settings": {},
        },
    )
    with patch(
        "app.tasks.workflow_error_alerts.send_workflow_error_alert.apply_async"
    ) as mock_apply:
        enqueue_workflow_error_alert_from_state(state)

    assert mock_apply.call_args.kwargs["queue"] == settings.DEFAULT_WORK_QUEUE
    assert mock_apply.call_args.kwargs["kwargs"]["payload"]["tenant_slug"] == "gelita"
