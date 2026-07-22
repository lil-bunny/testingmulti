import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.workflows.run_workflow_async", ignore_result=True)
def run_workflow_async(tenant_slug: str, workflow_name: str, payload: dict[str, Any]):
    """
    Run one graph attempt for a Work item, then start-next when serialized.

    Flow: ``WorkflowService.run``; if ``SERIALIZED_FLAG`` is set, ``finally``
    calls complete_and_start_next so the next buffered item can publish.
    """
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.lifecycle_run_serializer_service import (
        SERIALIZED_FLAG,
        LifecycleRunSerializerService,
    )
    from app.services.workflow_service import WorkflowService

    logger.info(
        "run_workflow_async start tenant_slug=%s workflow_name=%s workflow_instance_id=%s event_type=%s",
        tenant_slug,
        workflow_name,
        payload.get("workflow_instance_id"),
        payload.get("event_type"),
    )

    serialized = bool(payload.get(SERIALIZED_FLAG))
    lifecycle_id = str(payload.get("workflow_lifecycle_id") or "").strip()

    service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
    try:
        asyncio.run(
            service.run(
                tenant_slug=tenant_slug,
                workflow_name=workflow_name,
                payload=payload,
            )
        )
    finally:
        if serialized and lifecycle_id:
            lifecycle_run_serializer_service = LifecycleRunSerializerService()
            lifecycle_run_serializer_service.complete_and_start_next(
                lifecycle_id=lifecycle_id,
            )
