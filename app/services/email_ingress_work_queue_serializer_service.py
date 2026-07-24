"""Publish-bridge for the Pre-Lifecycle Work Queue (Heavy Ingress Work, keyed by email_id).

Mirrors ``LifecycleRunSerializerService`` at the Redis layer (same admit/complete
primitives via ``LifecycleRunQueueService``, different key scope) but never
resolves or creates a workflow lifecycle: at admit time no lifecycle exists yet.
The worker (``run_email_webhook``) is what eventually classifies the delivery and,
for sheet ingest, creates one lifecycle per tender row via the existing
``LifecycleRunSerializerService``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.services.lifecycle_run_queue_service import (
    LifecycleRunQueueService,
    email_ingress_work_queue_key,
)
from app.services.worker_queue_routing import apply_async_on_work_queue
from app.tasks.email_handlers import HANDLER_INBOUND_UNIPILE_EMAIL

logger = get_logger(__name__)


@dataclass(frozen=True)
class EmailIngressAdmitResult:
    """Result of admitting/chaining one Heavy Ingress Work Item."""

    email_id: str
    inbox_key: str
    status: str  # started | buffered | drained
    length: int | None = None
    celery_task_id: str | None = None


def _task_id(task: Any) -> str | None:
    return str(getattr(task, "id", None) or "") or None


class EmailIngressWorkQueueSerializerService:
    """
    Serialize Heavy Ingress Work per ``email_id`` (Pre-Lifecycle Work Queue).

    Flow: RPUSH one Heavy Ingress Work Item → Celery-publish only when the list
    length becomes 1; after the worker attempt finishes (success or failure),
    complete and start-next so a buffered duplicate delivery can run.
    """

    def __init__(self, run_queue: LifecycleRunQueueService | None = None) -> None:
        self._queue = run_queue or LifecycleRunQueueService()

    def admit(
        self,
        *,
        email_id: str,
        tenant_uuid: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> EmailIngressAdmitResult:
        """
        RPUSH one Heavy Ingress Work Item; publish only when it becomes the head.

        Outcomes: ``started`` when length becomes 1 (Celery publish); ``buffered``
        when another delivery's Heavy Ingress Work is already in flight for this
        ``email_id`` (e.g. a duplicate/retried webhook for the same delivery).
        """
        eid = str(email_id or "").strip()
        if not eid:
            raise ValueError("email_id required for Pre-Lifecycle Work Queue admit")

        inbox_key = email_ingress_work_queue_key(email_id=eid)
        work_item = {
            "tenant_uuid": tenant_uuid,
            "tenant_slug": tenant_slug,
            "payload": payload,
            "email_id": eid,
        }
        admit = self._queue.admit(inbox_key=inbox_key, work_item=work_item)
        if not admit.should_enqueue:
            logger.info(
                "email_ingress_work_queue buffered inbox_key=%s length=%s",
                inbox_key,
                admit.length,
            )
            return EmailIngressAdmitResult(
                email_id=eid,
                inbox_key=inbox_key,
                status="buffered",
                length=admit.length,
            )

        task = self._publish(tenant_slug=tenant_slug, work_item=work_item)
        tid = _task_id(task)
        logger.info(
            "email_ingress_work_queue started inbox_key=%s celery_task_id=%s",
            inbox_key,
            tid,
        )
        return EmailIngressAdmitResult(
            email_id=eid,
            inbox_key=inbox_key,
            status="started",
            length=admit.length,
            celery_task_id=tid,
        )

    def complete_and_start_next(self, *, email_id: str) -> EmailIngressAdmitResult | None:
        """
        After one worker attempt (success or failure): MULTI complete, then start-next.

        Outcomes: ``None`` when the queue drains (no chain needed); ``started``
        when the next buffered Heavy Ingress Work Item is published.
        """
        eid = str(email_id or "").strip()
        if not eid:
            return None

        inbox_key = email_ingress_work_queue_key(email_id=eid)
        complete = self._queue.complete(inbox_key=inbox_key)
        if not complete.should_chain:
            logger.info(
                "email_ingress_work_queue drained inbox_key=%s",
                inbox_key,
            )
            return None

        next_item = self._queue.peek_head(inbox_key=inbox_key)
        if next_item is None:
            logger.warning(
                "email_ingress_work_queue start_next empty_head inbox_key=%s "
                "remaining=%s",
                inbox_key,
                complete.remaining,
            )
            return None

        tenant_slug = str(next_item.get("tenant_slug") or "").strip()
        payload = next_item.get("payload")
        if not tenant_slug or not isinstance(payload, dict):
            logger.error(
                "email_ingress_work_queue start_next invalid_work_item inbox_key=%s",
                inbox_key,
            )
            return EmailIngressAdmitResult(
                email_id=eid,
                inbox_key=inbox_key,
                status="buffered",
                length=complete.remaining,
            )

        task = self._publish(tenant_slug=tenant_slug, work_item=next_item)
        tid = _task_id(task)
        logger.info(
            "email_ingress_work_queue start_next inbox_key=%s celery_task_id=%s",
            inbox_key,
            tid,
        )
        return EmailIngressAdmitResult(
            email_id=eid,
            inbox_key=inbox_key,
            status="started",
            length=complete.remaining,
            celery_task_id=tid,
        )

    @staticmethod
    def _publish(*, tenant_slug: str, work_item: dict[str, Any]) -> Any:
        from app.tasks.email import run_email_webhook

        return apply_async_on_work_queue(
            run_email_webhook,
            tenant_slug=tenant_slug,
            kwargs={
                "handler": HANDLER_INBOUND_UNIPILE_EMAIL,
                "tenant_uuid": work_item.get("tenant_uuid"),
                "tenant_slug": work_item.get("tenant_slug"),
                "payload": work_item.get("payload"),
                "email_id": work_item.get("email_id"),
            },
        )
