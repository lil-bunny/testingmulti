"""Unipile email Ingress accept helper (sync HTTP; no Celery hop)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.unipile_email import extract_email_id_or_none
from app.services.inbound_unipile_email_handler import process_inbound_unipile_email

logger = get_logger(__name__)


async def accept_inbound_unipile_email(
    *,
    tenant_uuid: str,
    tenant_slug: str,
    payload: dict[str, Any],
) -> tuple[str, str]:
    """
    Accept one Unipile delivery on the request path.

    Flow: tenant classify/gates → serialize-enqueue.
    Returns ``(email_id, status)``:
    ``accepted`` | ``buffered`` | ``skipped`` | ``no_match``.
    """
    email_id = extract_email_id_or_none(payload)
    if not email_id:
        raise ValueError("payload missing email_id")

    result = await process_inbound_unipile_email(
        tenant_uuid=tenant_uuid,
        tenant_slug=tenant_slug,
        payload=payload,
    )

    if result.outcome in ("enqueued", "processed"):
        status = "accepted"
    elif result.outcome == "buffered":
        status = "buffered"
    elif result.outcome == "skipped":
        status = "skipped"
    else:
        status = "no_match"

    logger.info(
        "inbound unipile email ingress_path email_id=%s tenant_slug=%s "
        "outcome=%s status=%s",
        email_id,
        tenant_slug,
        result.outcome,
        status,
    )
    return email_id, status
