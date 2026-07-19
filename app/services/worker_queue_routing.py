"""Choose Celery work queue at publish time (dedicated vs default).

See ``docs/celery-queues/``. Not a per-tenant queue registry.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.models.tenants import TenantSlug

logger = get_logger(__name__)


def resolve_work_queue(tenant_slug: str | None) -> str:
    """
    Return the Celery work queue for this tenant slug.

    T3RA → ``settings.T3RA_WORK_QUEUE``; otherwise ``settings.DEFAULT_WORK_QUEUE``.
    Blank slug → default queue and warning log (unguarded enqueue; never drop).
    """
    slug = (tenant_slug or "").strip()
    if not slug:
        logger.warning(
            "unguarded enqueue: missing tenant_slug; using default work queue=%s",
            settings.DEFAULT_WORK_QUEUE,
        )
        return settings.DEFAULT_WORK_QUEUE
    if slug == TenantSlug.T3RA:
        return settings.T3RA_WORK_QUEUE
    return settings.DEFAULT_WORK_QUEUE


def apply_async_on_work_queue(
    task: Any,
    *,
    tenant_slug: str | None,
    **apply_async_kwargs: Any,
) -> Any:
    """
    Call ``task.apply_async`` with ``queue`` from ``resolve_work_queue(tenant_slug)``.

    Forwards countdown/eta/expires/task_id/kwargs; overwrites any caller ``queue=``.
    """
    queue = resolve_work_queue(tenant_slug)
    apply_async_kwargs["queue"] = queue
    return task.apply_async(**apply_async_kwargs)
