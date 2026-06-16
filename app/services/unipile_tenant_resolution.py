"""Resolve Unipile webhook payloads to tenant UUID + graph slug."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.configs.tenant_configs import TENANT_CONFIGS
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.services.data_import_tenant_resolution import resolve_inbound_routing_tenant_match

logger = get_logger(__name__)


@dataclass(frozen=True)
class UnipileTenantContext:
    """Tenant row resolved from inbound recipient emails."""

    tenant_uuid: str
    tenant_slug: str


def resolve_unipile_tenant(*, payload: dict[str, Any]) -> UnipileTenantContext | None:
    """
    L1 routing: to/cc/bcc recipient emails → ``tenants.settings.inbound_routing_emails``
    → UUID + slug (single DB session).
    """
    match = run_with_repos(
        lambda repos: resolve_inbound_routing_tenant_match(
            payload=payload,
            tenants_repo=repos.tenants,
        )
    )
    if not match or not match.tenant_id:
        return None

    slug = (match.slug or "").strip()
    valid = frozenset(TENANT_CONFIGS.keys())

    if slug not in valid:
        logger.warning(
            "unipile tenant resolution: unknown slug=%r tenant_uuid=%s",
            slug,
            match.tenant_id,
        )
        return None

    return UnipileTenantContext(tenant_uuid=match.tenant_id, tenant_slug=slug)
