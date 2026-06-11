"""Enqueue background email webhook ingest with deterministic Celery task ids."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.logger import get_logger
from app.domain.delivery_locations_import import unipile_delivery_locations_attachment
from app.domain.load_tendering_import import email_load_tender_xlsx_attachment
from app.domain.unipile_email import build_unipile_attachment_fetch_context
from app.tasks.email import run_email_webhook
from app.tasks.email_handlers import (
    HANDLER_DELIVERY_LOCATIONS_IMPORT,
    HANDLER_LOAD_TENDERING_TENDER_CREATED,
)

logger = get_logger(__name__)

_INGEST_TASK_NAMESPACE = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def build_load_tendering_ingest_task_id(
    *,
    tenant_uuid: str,
    email_id: str,
    attachment_id: str,
) -> str:
    key = f"{tenant_uuid}:{email_id}:{attachment_id}:{HANDLER_LOAD_TENDERING_TENDER_CREATED}"
    return str(uuid.uuid5(_INGEST_TASK_NAMESPACE, key))


def enqueue_delivery_locations_import(
    *,
    payload: dict[str, Any],
    tenant_uuid: str,
) -> tuple[str, str]:
    """
    Queue background ingest for ``delivery_location.xlsx``.

    Returns ``(task_id, status)`` where status is ``queued`` or ``already_queued``.
    """
    attachment = unipile_delivery_locations_attachment(payload)
    if attachment is None:
        raise ValueError("payload has no delivery_location.xlsx attachment")

    fetch_ctx = build_unipile_attachment_fetch_context(payload, attachment)
    email_id = fetch_ctx.get("email_id")
    attachment_id = fetch_ctx.get("attachment_id")
    if not email_id or not attachment_id:
        raise ValueError("incomplete delivery locations attachment fetch context")

    task_id = str(
        uuid.uuid5(
            _INGEST_TASK_NAMESPACE,
            f"{tenant_uuid}:{email_id}:{attachment_id}:{HANDLER_DELIVERY_LOCATIONS_IMPORT}",
        )
    )
    kwargs = {
        "tenant_uuid": tenant_uuid,
        "payload": payload,
    }

    try:
        run_email_webhook.apply_async(
            kwargs={"handler": HANDLER_DELIVERY_LOCATIONS_IMPORT, **kwargs},
            task_id=task_id,
        )
        logger.info(
            "email webhook ingest queued handler=%s task_id=%s email_id=%s",
            HANDLER_DELIVERY_LOCATIONS_IMPORT,
            task_id,
            email_id,
        )
        return task_id, "queued"
    except Exception as exc:
        if not _is_duplicate_celery_task_id_error(exc):
            raise
        logger.info(
            "email webhook ingest already queued handler=%s task_id=%s email_id=%s",
            HANDLER_DELIVERY_LOCATIONS_IMPORT,
            task_id,
            email_id,
        )
        return task_id, "already_queued"


def enqueue_load_tendering_tender_created_ingest(
    *,
    payload: dict[str, Any],
    tenant_uuid: str,
    tenant_slug: str,
    graph_slug: str,
) -> tuple[str, str]:
    """
    Queue background ingest for Gelita xlsx tender_created.

    Returns ``(task_id, status)`` where status is ``queued`` or ``already_queued``.
    """
    attachment = email_load_tender_xlsx_attachment(payload)
    if attachment is None:
        raise ValueError("payload has no load-tender xlsx attachment")

    fetch_ctx = build_unipile_attachment_fetch_context(payload, attachment)
    email_id = fetch_ctx.get("email_id")
    attachment_id = fetch_ctx.get("attachment_id")
    if not email_id or not attachment_id:
        raise ValueError("incomplete xlsx attachment fetch context")

    task_id = build_load_tendering_ingest_task_id(
        tenant_uuid=tenant_uuid,
        email_id=email_id,
        attachment_id=attachment_id,
    )
    kwargs = {
        "tenant_uuid": tenant_uuid,
        "tenant_slug": tenant_slug,
        "graph_slug": graph_slug,
        "payload": payload,
    }

    try:
        run_email_webhook.apply_async(
            kwargs={"handler": HANDLER_LOAD_TENDERING_TENDER_CREATED, **kwargs},
            task_id=task_id,
        )
        logger.info(
            "email webhook ingest queued handler=%s task_id=%s email_id=%s",
            HANDLER_LOAD_TENDERING_TENDER_CREATED,
            task_id,
            email_id,
        )
        return task_id, "queued"
    except Exception as exc:
        if not _is_duplicate_celery_task_id_error(exc):
            raise
        logger.info(
            "email webhook ingest already queued handler=%s task_id=%s email_id=%s",
            HANDLER_LOAD_TENDERING_TENDER_CREATED,
            task_id,
            email_id,
        )
        return task_id, "already_queued"


def _is_duplicate_celery_task_id_error(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "already exists" in msg or "duplicate" in msg
