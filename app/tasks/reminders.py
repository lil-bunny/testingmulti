import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.reminders.trigger_workflow_reminder", ignore_result=True)
def trigger_workflow_reminder(payload: dict[str, Any]):
    """Delayed re-run of any workflow with ``reminder_due`` / ``escalation_due`` (or similar)."""
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.workflow_service import WorkflowService

    workflow_service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
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

    asyncio.run(
        workflow_service.run(
            tenant_slug=tenant_slug,
            workflow_name=workflow_name,
            payload=payload,
        )
    )
