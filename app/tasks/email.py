"""Celery consumer for the Pre-Lifecycle Work Queue (Heavy Ingress Work)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger
from app.tasks.email_handlers import get_email_webhook_handler

logger = get_logger(__name__)

# Stable broker name: keep when renaming module so in-flight Redis messages still resolve.
_EMAIL_WEBHOOK_TASK_NAME = "app.tasks.email_webhook_ingest.run"

_FAILED_EMAIL_INGRESS_KEY = "failed:email_ingress"


@celery_app.task(name=_EMAIL_WEBHOOK_TASK_NAME, ignore_result=True)
def run_email_webhook(
    handler: str,
    *,
    tenant_uuid: str,
    tenant_slug: str,
    payload: dict[str, Any],
    email_id: str,
) -> None:
    """
    Run one Heavy Ingress Work Item, then start-next on the Pre-Lifecycle Work Queue.

    Mirrors ``run_workflow_async``: no Celery-level autoretry (fail fast, log to
    ``failed:email_ingress`` for ops, re-raise once); ``finally`` always calls
    ``complete_and_start_next`` so a buffered duplicate delivery for the same
    ``email_id`` can run next, even after a failure. Attachment-fetch transient
    errors already retry at the Unipile-client layer
    (``fetch_email_attachment_bytes_with_retry``); this task does not add a
    second, coarser retry on top of that.
    """
    from app.integrations.redis.client import get_redis_client
    from app.services.email_ingress_work_queue_serializer_service import (
        EmailIngressWorkQueueSerializerService,
    )

    logger.info(
        "run_email_webhook start handler=%s tenant_uuid=%s tenant_slug=%s email_id=%s",
        handler,
        tenant_uuid,
        tenant_slug,
        email_id,
    )

    fn = get_email_webhook_handler(handler)
    try:
        asyncio.run(
            fn(
                tenant_uuid=tenant_uuid,
                tenant_slug=tenant_slug,
                payload=payload,
            )
        )
    except Exception as exc:
        redis = get_redis_client()
        redis.rpush(
            _FAILED_EMAIL_INGRESS_KEY,
            json.dumps(
                {
                    "handler": handler,
                    "tenant_uuid": tenant_uuid,
                    "tenant_slug": tenant_slug,
                    "email_id": email_id,
                    "payload": payload,
                    "error": str(exc),
                },
                default=str,
            ),
        )
        raise
    finally:
        email_ingress_work_queue_serializer_service = EmailIngressWorkQueueSerializerService()
        email_ingress_work_queue_serializer_service.complete_and_start_next(email_id=email_id)

    logger.info(
        "run_email_webhook done handler=%s email_id=%s",
        handler,
        email_id,
    )
