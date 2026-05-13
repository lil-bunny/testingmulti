import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.workflows.run_workflow_async", ignore_result=True)
def run_workflow_async(tenant_id: str, workflow_name: str, payload: dict[str, Any]):
    """Async workflow launcher used by webhook ingress handlers."""
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.workflow_service import WorkflowService

    logger.info(
        "run_workflow_async start tenant_id=%s workflow_name=%s workflow_instance_id=%s event_type=%s",
        tenant_id,
        workflow_name,
        payload.get("workflow_instance_id"),
        payload.get("event_type"),
    )

    service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
    asyncio.run(
        service.run(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            payload=payload,
        )
    )
