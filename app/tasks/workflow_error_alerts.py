"""Celery tasks for workflow error alert delivery."""

from __future__ import annotations

from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger
from app.domain.workflow_error_alert_payload import WorkflowErrorAlertPayload
from app.services.unipile_service import UnipileException
from app.services.workflow_error_alert_service import (
    WorkflowErrorAlertDeliveryError,
    WorkflowErrorAlertService,
)

logger = get_logger(__name__)

_TASK_NAME = "app.tasks.workflow_error_alerts.send_workflow_error_alert"
_RETRY_KWARGS = {"max_retries": 3, "countdown": 60}


@celery_app.task(
    name=_TASK_NAME,
    ignore_result=True,
    autoretry_for=(UnipileException, WorkflowErrorAlertDeliveryError),
    retry_kwargs=_RETRY_KWARGS,
    retry_jitter=True,
)
def send_workflow_error_alert(payload: dict[str, Any]) -> None:
    """Celery entrypoint: deliver configured alerts for one workflow error."""
    parsed = WorkflowErrorAlertPayload.model_validate(payload)
    logger.info(
        "send_workflow_error_alert lifecycle_id=%s error_code=%s",
        parsed.workflow_lifecycle_id,
        parsed.error.get("code"),
    )
    workflow_error_alert_service = WorkflowErrorAlertService()
    workflow_error_alert_service.send_workflow_error_alert(parsed)
