"""Resolve tenants.id (UUID) for email gateway webhooks → data_import flows."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.config import settings
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.unipile_email import resolve_unipile_webhook_base_name

logger = get_logger(__name__)


@runtime_checkable
class _TenantsLookup(Protocol):
    def find_tenant_id_by_email_webhook_name(self, webhook_name: str) -> str | None: ...


def resolve_email_data_import_tenant_id(
    *,
    payload: dict[str, Any],
    tenants_repo: _TenantsLookup | None = None,
) -> str | None:
    """
    Match ``payload["webhook_name"]`` (``{email_webhook_name}_{ENV}``) to
    ``tenants.settings.email_webhook_name``.

    Returns ``None`` when missing, env mismatch, or no row — callers skip attachment/data_import
    unless the workflow requires a mapping (e.g. load_tendering).
    """
    webhook_name = str(payload.get("webhook_name") or "")
    base_name = resolve_unipile_webhook_base_name(webhook_name, settings.ENV)
    if not base_name:
        if webhook_name.strip():
            logger.warning(
                "email webhook data_import tenant: invalid webhook_name=%r env=%r",
                webhook_name.strip(),
                settings.ENV,
            )
        return None

    if tenants_repo is not None:
        tid = tenants_repo.find_tenant_id_by_email_webhook_name(base_name)
    else:
        tid = run_with_repos(
            lambda repos: repos.tenants.find_tenant_id_by_email_webhook_name(base_name)
        )
    if tid:
        return tid.strip()

    logger.warning(
        "email webhook data_import tenant: no tenants row for settings.email_webhook_name=%r",
        base_name,
    )
    return None
