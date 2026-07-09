"""Celery tasks for background email webhook processing."""

from __future__ import annotations

import asyncio
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger
from app.services.unipile_service import UnipileException
from app.tasks.email_handlers import get_email_webhook_handler

logger = get_logger(__name__)

# Stable broker name: keep when renaming module so in-flight Redis messages still resolve.
_EMAIL_WEBHOOK_TASK_NAME = "app.tasks.email_webhook_ingest.run"

# Celery autoretry: full ingest re-run after app-level attachment retries exhaust.
# Uses UnipileException (httpx/Unipile), not requests.RequestException.
_EMAIL_WEBHOOK_RETRY_KWARGS = {"max_retries": 3, "countdown": 60}


@celery_app.task(
    name=_EMAIL_WEBHOOK_TASK_NAME,
    ignore_result=True,
    bind=True,
    autoretry_for=(UnipileException,),
    retry_kwargs=_EMAIL_WEBHOOK_RETRY_KWARGS,
    retry_jitter=True,
)
def run_email_webhook(self, handler: str, **kwargs: Any) -> None:
    """
    Dispatch email webhook ingest by handler key.

    On UnipileException, Celery retries the full handler after ~60s (max 3 retries).
    Import/tender steps are idempotent; partial workflow enqueue on crash+retry is a
    known edge case (see load_tendering_email_ingest_service).
    """
    fn = get_email_webhook_handler(handler)

    logger.info(
        "run_email_webhook start handler=%s tenant_uuid=%s celery_retry=%s",
        handler,
        kwargs.get("tenant_uuid"),
        self.request.retries,
    )
    asyncio.run(fn(**kwargs))
    logger.info(
        "run_email_webhook done handler=%s celery_retry=%s",
        handler,
        self.request.retries,
    )
