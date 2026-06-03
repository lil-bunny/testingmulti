"""Map ``tenants.id`` (UUID) + webhook context to LangGraph ``TENANT_CONFIGS`` keys."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.configs.tenant_configs import TENANT_CONFIGS
from app.core.logger import get_logger
from app.core.service_db import run_with_repos

if TYPE_CHECKING:
    from app.repositories.tenants_db_repository import TenantsDbRepository

logger = get_logger(__name__)

_DEFAULT_GRAPH_TENANT_ID = "t3ra"


def resolve_workflow_graph_tenant_id(
    *,
    data_import_tenant_id: str,
    webhook_name: str,
    tenants_repo: TenantsDbRepository | None = None,
) -> str:
    """
    Pick Celery/graph ``tenant_id``: ``tenants.slug`` wins when it equals a ``TENANT_CONFIGS``
    top-level key, else ``webhook_name`` when it matches such a key, else ``t3ra``.
    """
    from app.repositories.tenants_db_repository import TenantsDbRepository

    valid = frozenset(TENANT_CONFIGS.keys())
    tenant_uuid = str(data_import_tenant_id or "").strip()
    hook = str(webhook_name or "").strip()

    stored_key: str | None = None
    if tenant_uuid:
        if tenants_repo is not None:
            raw = tenants_repo.get_slug_for_tenant_uuid(tenant_uuid)
        else:
            raw = run_with_repos(
                lambda repos: repos.tenants.get_slug_for_tenant_uuid(tenant_uuid)
            )
        if raw:
            cand = raw.strip()
            if cand in valid:
                stored_key = cand
            elif cand:
                logger.info(
                    "workflow_graph_tenant: ignoring unknown slug=%r tenant_uuid=%s "
                    "(not in TENANT_CONFIGS)",
                    cand,
                    tenant_uuid,
                )

    if stored_key:
        logger.info(
            "workflow_graph_tenant: tenant_id=%r resolved_from=tenants.slug "
            "data_import_tenant_id=%s",
            stored_key,
            tenant_uuid,
        )
        return stored_key

    if hook and hook in valid:
        logger.info(
            "workflow_graph_tenant: tenant_id=%r resolved_from=webhook_name "
            "data_import_tenant_id=%s",
            hook,
            tenant_uuid,
        )
        return hook

    logger.info(
        "workflow_graph_tenant: tenant_id=%r resolved_from=default data_import_tenant_id=%s",
        _DEFAULT_GRAPH_TENANT_ID,
        tenant_uuid,
    )
    return _DEFAULT_GRAPH_TENANT_ID
