"""Resolve tenants.id (UUID) for email gateway webhooks → data_import flows."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from app.core.logger import get_logger
from app.repositories.tenants_db_repository import TenantsDbRepository

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
    Match ``payload["webhook_name"]`` to ``tenants.settings.email_webhook_name``.

    Returns ``None`` when missing or no row — callers skip attachment/data_import unless the
    workflow requires a mapping (e.g. load_tendering).

    Blank / missing ``webhook_name`` is rejected in the repository layer (no DB query); non-blank
    names that do not match any ``tenants.settings.email_webhook_name`` log a warning.
    """
    webhook_name = str(payload.get("webhook_name") or "")

    repo = tenants_repo or TenantsDbRepository()
    tid = repo.find_tenant_id_by_email_webhook_name(webhook_name)
    if tid:
        return tid.strip()

    if webhook_name.strip():
        logger.warning(
            "email webhook data_import tenant: no tenants row for settings.email_webhook_name=%r",
            webhook_name.strip(),
        )
    return None
