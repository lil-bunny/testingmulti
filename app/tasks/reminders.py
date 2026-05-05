import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.reminders.trigger_pod_reminder", ignore_result=True)
def trigger_pod_reminder(payload: dict[str, Any]):
    """
    After Celery countdown (24h / 48h), re-run pod_lifecycle with ``reminder_due``.
    Email delivery runs in the graph via ``send_email`` (no duplicate Unipile send here).
    """
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.workflow_service import WorkflowService

    service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
    logger.info(
        "trigger_pod_reminder start reminder_step=%s tenant_id=%s workflow_instance_id=%s "
        "shipment_id=%s thread_id=%s account_id=%s subject=%r",
        payload.get("reminder_step"),
        payload.get("tenant_id"),
        payload.get("workflow_instance_id"),
        payload.get("shipment_id"),
        payload.get("thread_id"),
        payload.get("account_id"),
        payload.get("subject"),
    )

    asyncio.run(
        service.run(
            tenant_id=payload["tenant_id"],
            workflow_name="pod_lifecycle",
            payload=payload,
        )
    )
