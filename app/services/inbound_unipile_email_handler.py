"""Unified Celery ingress handler for Unipile email webhooks."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger
from app.domain.ingress_result import IngressResult
from app.domain.unipile_email import extract_email_id_or_none
from app.models.tenants import TenantSlug
from app.services.communications.service import CommunicationsService
from app.services.gelita_email_ingress_service import GelitaEmailIngressService
from app.services.t3ra_email_ingress_service import T3raEmailIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext

logger = get_logger(__name__)


async def process_inbound_unipile_email(
    *,
    tenant_uuid: str,
    tenant_slug: str,
    payload: dict[str, Any],
) -> IngressResult:
    """
    Celery handler ``inbound.unipile_email``: record comm, delegate L2 to tenant ingress services.

    HTTP edge only enqueues this task; all guards and ``run_workflow_async`` calls happen here.
    """
    # Persist inbound comm first — tenant L2 services receive communication_id for workflow payloads.
    communications_service = CommunicationsService()
    communication_id = communications_service.record_or_resolve_inbound(
        tenant_uuid,
        payload,
    )
    tenant = UnipileTenantContext(
        tenant_uuid=tenant_uuid,
        tenant_slug=tenant_slug,
    )
    email_id = extract_email_id_or_none(payload)

    # Tenant-specific L2: Gelita load_tendering branches vs T3RA classifier paths.
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
        # Phase 1: only Gelita + T3RA; other slugs should not reach L1 routing in production.
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
