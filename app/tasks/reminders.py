import asyncio
from typing import Any

from app.celery_app import celery_app


@celery_app.task(name="app.tasks.reminders.trigger_pod_reminder", ignore_result=True)
def trigger_pod_reminder(payload: dict[str, Any]):
    """
    Invoke pod_lifecycle reminder path for an existing workflow instance.
    """
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.workflow_service import WorkflowService

    service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
    asyncio.run(
        service.run(
            tenant_id=payload["tenant_id"],
            workflow_name="pod_lifecycle",
            payload=payload,
        )
    )
