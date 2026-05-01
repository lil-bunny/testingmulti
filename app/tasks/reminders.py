import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.tasks.reminders.trigger_pod_reminder", ignore_result=True)
def trigger_pod_reminder(payload: dict[str, Any]):
    """
    Invoke pod_lifecycle reminder path for an existing workflow instance.
    """
    from app.repositories.tenant_repo import TenantRepository
    from app.repositories.workflow_repo import WorkflowRepository
    from app.services.workflow_service import WorkflowService
    from app.tools.email import send_unipile_thread_reply

    tid = (payload.get("thread_id") or "").strip()
    acc = (settings.UNIPILE_ACCOUNT_ID or "").strip()
    if settings.UNIPILE_API_KEY and tid and acc:
        ok = send_unipile_thread_reply(
            thread_id=tid,
            account_id=acc,
            subject=str(payload.get("subject") or "POD reminder"),
            body=str(
                (payload.get("body") or "").strip() or settings.POD_REMINDER_EMAIL_BODY
            ),
        )
        if ok:
            logger.info("Unipile reminder reply sent; thread_id=%s subject=%s", tid[:48], payload.get("subject"))
        else:
            logger.warning(
                "Unipile reminder reply did not send (see warnings above); thread_id=%s",
                tid[:48],
            )
    elif not settings.UNIPILE_API_KEY:
        logger.info("Unipile reminder skipped: UNIPILE_API_KEY not set")
    elif not tid:
        logger.info("Unipile reminder skipped: payload has no thread_id")
    elif not acc:
        logger.info("Unipile reminder skipped: UNIPILE_ACCOUNT_ID not set")

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
