"""Enqueue unified Unipile email ingress tasks with deterministic Celery task ids."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.unipile_email import extract_email_id_or_none
from app.services.worker_queue_routing import apply_async_on_work_queue
from app.tasks.email_handlers import HANDLER_INBOUND_UNIPILE_EMAIL

logger = get_logger(__name__)

_INGRESS_TASK_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def build_inbound_ingress_task_id(*, tenant_uuid: str, email_id: str) -> str:
    """Deterministic Celery task id from tenant + Unipile ``email_id`` (HTTP edge idempotency)."""
    key = f"{tenant_uuid}:{email_id}"
    return str(uuid.uuid5(_INGRESS_TASK_NAMESPACE, key))


def enqueue_inbound_unipile_email(
    *,
    tenant_uuid: str,
    tenant_slug: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """
    Queue one ingress task per Unipile email delivery.

    Uses a deterministic ``task_id`` so Unipile retries return ``already_queued`` instead of
    spawning parallel workers. Called from the thin ``POST /webhook/email`` handler.
    """
    from app.tasks.email import run_email_webhook

    email_id = extract_email_id_or_none(payload)
    if not email_id:
        raise ValueError("payload missing email_id")

    task_id = build_inbound_ingress_task_id(
        tenant_uuid=tenant_uuid,
        email_id=email_id,
    )
    kwargs = {
        "tenant_uuid": tenant_uuid,
        "tenant_slug": tenant_slug,
        "payload": payload,
    }

    try:
        apply_async_on_work_queue(
            run_email_webhook,
            tenant_slug=tenant_slug,
            kwargs={"handler": HANDLER_INBOUND_UNIPILE_EMAIL, **kwargs},
            task_id=task_id,
        )
        logger.info(
            "inbound unipile email queued handler=%s task_id=%s email_id=%s tenant_slug=%s",
            HANDLER_INBOUND_UNIPILE_EMAIL,
            task_id,
            email_id,
            tenant_slug,
        )
        return task_id, "queued"
    except Exception as exc:
        # Duplicate task_id — first delivery still queued or finished; safe to ACK retry.
        if not _is_duplicate_celery_task_id_error(exc):
            raise
        logger.info(
            "inbound unipile email already queued handler=%s task_id=%s email_id=%s",
            HANDLER_INBOUND_UNIPILE_EMAIL,
            task_id,
            email_id,
        )
        return task_id, "already_queued"


def _is_duplicate_celery_task_id_error(exc: BaseException) -> bool:
    """True when Redis already holds this deterministic ``task_id``."""
    msg = str(exc).lower()
    return "already exists" in msg or "duplicate" in msg
