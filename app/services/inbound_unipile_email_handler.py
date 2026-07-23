"""Dispatch Unipile email to tenant ingress services (request path)."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.unipile_email import extract_email_id_or_none
from app.models.tenants import TenantSlug
from app.services.gelita_email_ingress_service import GelitaEmailIngressService
from app.services.t3ra_email_ingress_service import T3raEmailIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext

logger = get_logger(__name__)


async def process_inbound_unipile_email(
    *,
    tenant_uuid: str,
    tenant_slug: str,
    payload: dict[str, Any],
    communication_id: str | None = None,
) -> IngressResult:
    """
    Route one inbound email to Gelita or T3RA ingress.

    Comms persist later in graph task prep. ``communication_id`` is optional when
    already known; otherwise left unset until the graph Celery task runs.
    """
    tenant = UnipileTenantContext(
        tenant_uuid=tenant_uuid,
        tenant_slug=tenant_slug,
    )
    email_id = extract_email_id_or_none(payload)

    if tenant_slug == TenantSlug.GELITA:
        gelita_email_ingress_service = GelitaEmailIngressService()
        result = await gelita_email_ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=communication_id,
        )
    elif tenant_slug == TenantSlug.T3RA:
        t3ra_email_ingress_service = T3raEmailIngressService()
        result = await t3ra_email_ingress_service.process(
            payload=payload,
            tenant=tenant,
            communication_id=communication_id,
        )
    else:
        logger.warning(
            "inbound unipile email unsupported tenant_slug=%r email_id=%s",
            tenant_slug,
            email_id,
        )
        result = IngressResult(
            outcome="no_match",
            reason="unsupported_tenant",
        )

    logger.info(
        "inbound unipile email ingress outcome=%s event_type=%s reason=%s "
        "execution_count=%s tenant_slug=%s email_id=%s communication_id=%s",
        result.outcome,
        result.event_type,
        result.reason,
        len(result.execution_ids),
        tenant_slug,
        email_id,
        communication_id,
    )
    return result
