"""Resolve tenants.id (UUID) for email gateway webhooks → data_import flows."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.unipile_email import extract_recipient_emails
from app.exceptions import TenantResolutionError
from app.repositories.tenants_db_repository import InboundRoutingTenantMatch

logger = get_logger(__name__)


@runtime_checkable
class _TenantsLookup(Protocol):
    def find_by_inbound_routing_emails(
        self, emails: list[str]
    ) -> InboundRoutingTenantMatch: ...


def resolve_inbound_routing_tenant_match(
    *,
    payload: dict[str, Any],
    tenants_repo: _TenantsLookup | None = None,
) -> InboundRoutingTenantMatch | None:
    """
    Match recipient emails (to/cc/bcc) against ``tenants.settings.inbound_routing_emails``.

    Returns a single match or ``None`` when no recipients, no row, or multiple tenants match.
    """
    emails = extract_recipient_emails(payload)
    if not emails:
        logger.warning("email webhook data_import tenant: no recipient emails in payload")
        return None

    if tenants_repo is not None:
        db_match = tenants_repo.find_by_inbound_routing_emails(emails)
    else:
        db_match = run_with_repos(
            lambda repos: repos.tenants.find_by_inbound_routing_emails(emails)
        )

    if db_match.match_count == 0:
        logger.warning(
            "email webhook data_import tenant: no tenants row for inbound_routing_emails "
            "recipients=%r",
            emails,
        )
        return None

    if db_match.match_count > 1:
        logger.warning(
            "email webhook data_import tenant: multiple tenants match recipients=%r",
            emails,
        )
        raise TenantResolutionError("multiple tenants matched")

    return db_match


def resolve_email_data_import_tenant_id(
    *,
    payload: dict[str, Any],
    tenants_repo: _TenantsLookup | None = None,
) -> str | None:
    """
    Match recipient emails (to/cc/bcc) against ``tenants.settings.inbound_routing_emails``.

    Returns ``None`` when no recipients, no row, or multiple distinct tenants match.
    """
    match = resolve_inbound_routing_tenant_match(payload=payload, tenants_repo=tenants_repo)
    if not match or not match.tenant_id:
        return None
    return match.tenant_id.strip() or None
