"""Resolve Unipile webhook payloads to tenant UUID + graph slug."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.configs.tenant_configs import TENANT_CONFIGS
from app.core.config import settings
from app.domain.unipile_email import resolve_unipile_webhook_base_name
from app.repositories.tenants_db_repository import get_slug_for_tenant_uuid
from app.services.data_import_tenant_resolution import resolve_email_data_import_tenant_id
from app.services.workflow_graph_tenant_resolution import resolve_workflow_graph_tenant_id


@dataclass(frozen=True)
class UnipileTenantContext:
    """Tenant row resolved from ``payload['webhook_name']``."""

    tenant_uuid: str
    tenant_slug: str


def resolve_unipile_tenant(*, payload: dict[str, Any]) -> UnipileTenantContext | None:
    """
    L1 routing: ``webhook_name`` → ``tenants.settings.email_webhook_name`` → UUID + slug.

    ``tenant_slug`` prefers ``tenants.slug`` when it is a ``TENANT_CONFIGS`` key, else
    ``webhook_name`` when that key exists, else graph default resolution.
    """
    tenant_uuid = resolve_email_data_import_tenant_id(payload=payload)
    if not tenant_uuid:
        return None

    webhook_name = resolve_unipile_webhook_base_name(
        str(payload.get("webhook_name") or ""),
        settings.ENV,
    ) or ""
    slug = (get_slug_for_tenant_uuid(tenant_uuid) or "").strip()
    valid = frozenset(TENANT_CONFIGS.keys())

    if slug not in valid:
        if webhook_name in valid:
            slug = webhook_name
        else:
            slug = resolve_workflow_graph_tenant_id(
                data_import_tenant_id=tenant_uuid,
                webhook_name=webhook_name,
            )

    if slug not in valid:
        return None

    return UnipileTenantContext(tenant_uuid=tenant_uuid, tenant_slug=slug)
