from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.reminders.trigger_workflow_reminder", ignore_result=True)
def trigger_workflow_reminder(payload: dict[str, Any]):
    """
    Reminder fire: serialize-enqueue the graph Work item (no in-process LangGraph).

    Countdown scheduling stays on Celery; this task only wakes the lifecycle
    run queue so the reminder graph starts under the same serialize rules.
    """
    from app.services.lifecycle_run_serializer_service import LifecycleRunSerializerService

    tenant_slug = str(payload.get("tenant_slug") or "").strip()
    workflow_name = str(payload.get("workflow_name") or "").strip()
    if not tenant_slug or not workflow_name:
        logger.error(
            "trigger_workflow_reminder missing tenant_slug or workflow_name payload_keys=%s",
            sorted(payload.keys()),
        )
        return

    logger.info(
        "trigger_workflow_reminder workflow_name=%s tenant_slug=%s event_type=%s "
        "reminder_step=%s workflow_lifecycle_id=%s",
        workflow_name,
        tenant_slug,
        payload.get("event_type"),
        payload.get("reminder_step"),
        payload.get("workflow_lifecycle_id"),
    )

    body = dict(payload)
    tenant_id = str(body.get("tenant_id") or tenant_slug).strip()
    lifecycle_run_serializer_service = LifecycleRunSerializerService()
    result = lifecycle_run_serializer_service.resolve_then_enqueue(
        tenant_id=tenant_id,
        tenant_slug=tenant_slug,
        workflow_name=workflow_name,
        payload=body,
    )
    logger.info(
        "trigger_workflow_reminder serialize status=%s lifecycle_id=%s celery_task_id=%s",
        result.status,
        result.lifecycle_id,
        result.celery_task_id,
    )
