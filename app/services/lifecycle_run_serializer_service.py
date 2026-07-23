"""Serialize-enqueue and start-next for per-lifecycle graph starts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.services.lifecycle_run_queue_service import (
    LifecycleRunQueueService,
    lifecycle_run_queue_key,
)
from app.services.worker_queue_routing import apply_async_on_work_queue
from app.services.workflow_lifecycle_service import WorkflowLifecycleService

logger = get_logger(__name__)

# Stamped on payload so run_workflow_async finally knows to start-next.
SERIALIZED_FLAG = "_lifecycle_run_serialized"


@dataclass(frozen=True)
class SerializeEnqueueResult:
    """Result of serialize-enqueue (RPUSH + optional Celery publish)."""

    lifecycle_id: str
    inbox_key: str
    status: str  # started | buffered | drained
    length: int | None = None
    celery_task_id: str | None = None
    workflow_lifecycle_id: str | None = None


def _task_id(task: Any) -> str | None:
    return str(getattr(task, "id", None) or "") or None


class LifecycleRunSerializerService:
    """
    Publish-bridge for per-lifecycle graph starts.

    Flow: resolve lifecycle id → RPUSH Work item → Celery-publish only when the
    list length becomes 1; after a graph task finishes, complete and start-next.
    """

    def __init__(
        self,
        run_queue: LifecycleRunQueueService | None = None,
        lifecycle_service: WorkflowLifecycleService | None = None,
    ) -> None:
        self._queue = run_queue or LifecycleRunQueueService()
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()

    def resolve_then_enqueue(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        workflow_name: str,
        payload: dict[str, Any],
    ) -> SerializeEnqueueResult:
        """
        Ensure ``workflow_lifecycle_id`` then serialize-enqueue the Work item.

        Creates/links lifecycle when missing; stamps shipment linkage when created.
        """
        body = dict(payload)
        existing = str(body.get("workflow_lifecycle_id") or "").strip()
        if not existing:
            resolution = self._lifecycle.resolve_or_create_lifecycle(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                payload=body,
            )
            body["workflow_lifecycle_id"] = resolution.workflow_lifecycle_id
            self._lifecycle.ensure_lifecycle_shipment_linked(
                lifecycle_id=resolution.workflow_lifecycle_id,
                tenant_id=tenant_id,
                payload=body,
            )
        return self.enqueue(
            tenant_slug=tenant_slug,
            workflow_name=workflow_name,
            payload=body,
        )

    def enqueue(
        self,
        *,
        tenant_slug: str,
        workflow_name: str,
        payload: dict[str, Any],
    ) -> SerializeEnqueueResult:
        """
        RPUSH a Work item and optionally publish ``run_workflow_async``.

        Requires ``workflow_lifecycle_id`` on the payload. Outcomes: ``started``
        when length becomes 1 (Celery publish); ``buffered`` when another run
        is already in flight for that lifecycle.
        """
        from app.tasks.workflows import run_workflow_async

        lid = str(payload.get("workflow_lifecycle_id") or "").strip()
        if not lid:
            raise ValueError(
                "workflow_lifecycle_id required for serialize-enqueue "
                "(use resolve_then_enqueue)"
            )

        body = dict(payload)
        body[SERIALIZED_FLAG] = True
        inbox_key = lifecycle_run_queue_key(lifecycle_id=lid)
        work_item = {
            "tenant_slug": tenant_slug,
            "workflow_name": workflow_name,
            "payload": body,
        }
        admit = self._queue.admit(inbox_key=inbox_key, work_item=work_item)
        if not admit.should_enqueue:
            return SerializeEnqueueResult(
                lifecycle_id=lid,
                inbox_key=inbox_key,
                status="buffered",
                length=admit.length,
                workflow_lifecycle_id=lid,
            )

        task = apply_async_on_work_queue(
            run_workflow_async,
            tenant_slug=tenant_slug,
            kwargs={
                "tenant_slug": tenant_slug,
                "workflow_name": workflow_name,
                "payload": body,
            },
        )
        tid = _task_id(task)
        logger.info(
            "lifecycle_run_serializer started inbox_key=%s celery_task_id=%s "
            "workflow_name=%s",
            inbox_key,
            tid,
            workflow_name,
        )
        return SerializeEnqueueResult(
            lifecycle_id=lid,
            inbox_key=inbox_key,
            status="started",
            length=admit.length,
            celery_task_id=tid,
            workflow_lifecycle_id=lid,
        )

    def complete_and_start_next(self, *, lifecycle_id: str) -> SerializeEnqueueResult | None:
        """
        After a graph Celery attempt: MULTI complete, then publish the next head.

        Outcomes: ``drained`` when the list is empty; ``started`` when the next
        Work item is published; ``buffered`` on invalid head (left for ops).
        """
        from app.tasks.workflows import run_workflow_async

        lid = str(lifecycle_id or "").strip()
        if not lid:
            return None

        inbox_key = lifecycle_run_queue_key(lifecycle_id=lid)
        complete = self._queue.complete(inbox_key=inbox_key)
        if not complete.should_chain:
            return SerializeEnqueueResult(
                lifecycle_id=lid,
                inbox_key=inbox_key,
                status="drained",
                length=0,
                workflow_lifecycle_id=lid,
            )

        next_item = self._queue.peek_head(inbox_key=inbox_key)
        if next_item is None:
            logger.warning(
                "lifecycle_run_serializer start_next empty_head inbox_key=%s "
                "remaining=%s",
                inbox_key,
                complete.remaining,
            )
            return SerializeEnqueueResult(
                lifecycle_id=lid,
                inbox_key=inbox_key,
                status="drained",
                length=complete.remaining,
                workflow_lifecycle_id=lid,
            )

        tenant_slug = str(next_item.get("tenant_slug") or "").strip()
        workflow_name = str(next_item.get("workflow_name") or "").strip()
        payload = next_item.get("payload")
        if not tenant_slug or not workflow_name or not isinstance(payload, dict):
            logger.error(
                "lifecycle_run_serializer start_next invalid_work_item "
                "inbox_key=%s",
                inbox_key,
            )
            return SerializeEnqueueResult(
                lifecycle_id=lid,
                inbox_key=inbox_key,
                status="buffered",
                length=complete.remaining,
                workflow_lifecycle_id=lid,
            )

        body = dict(payload)
        body[SERIALIZED_FLAG] = True
        if not str(body.get("workflow_lifecycle_id") or "").strip():
            body["workflow_lifecycle_id"] = lid

        task = apply_async_on_work_queue(
            run_workflow_async,
            tenant_slug=tenant_slug,
            kwargs={
                "tenant_slug": tenant_slug,
                "workflow_name": workflow_name,
                "payload": body,
            },
        )
        tid = _task_id(task)
        logger.info(
            "lifecycle_run_serializer start_next inbox_key=%s celery_task_id=%s "
            "workflow_name=%s",
            inbox_key,
            tid,
            workflow_name,
        )
        return SerializeEnqueueResult(
            lifecycle_id=lid,
            inbox_key=inbox_key,
            status="started",
            length=complete.remaining,
            celery_task_id=tid,
            workflow_lifecycle_id=lid,
        )
