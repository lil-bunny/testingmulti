"""Postgres ``tenants`` table lookups (app-level tenant UUID ``id``, JSON ``settings``)."""

from __future__ import annotations

from typing import Optional

import psycopg

from app.core.config import settings


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


def _table() -> str:
    t = settings.TENANTS_TABLE.strip()
    return t if t else "tenants"


def find_tenant_id_by_settings_email_webhook_name(webhook_name: str) -> Optional[str]:
    """
    Return ``tenants.id`` (UUID string) where ``settings`` JSON contains
    ``email_webhook_name`` equal to ``webhook_name`` (exact match).

    Ignores whitespace-only ``webhook_name``. If multiple rows match, logs and returns the
    first by ``id``.
    """
    from app.core.logger import get_logger

    logger = get_logger(__name__)
    needle = webhook_name.strip()
    if not needle:
        return None

    sql = (
        f"SELECT id::text FROM {_table()} "
        "WHERE settings IS NOT NULL "
        "AND (settings::jsonb ->> 'email_webhook_name') = %s "
        "ORDER BY id LIMIT 3"
    )
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (needle,))
            rows = cur.fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "tenants lookup: multiple rows match email_webhook_name=%r (%s ids); "
            "using first",
            needle,
            len(rows),
        )
    return str(rows[0][0])


def get_settings_workflow_graph_tenant_id(tenant_uuid: str) -> Optional[str]:
    """
    Return ``settings.workflow_graph_tenant_id`` from ``tenants`` row ``id``.
    Blank or unset values return ``None``.
    """
    needle = tenant_uuid.strip()
    if not needle:
        return None
    sql = (
        f"SELECT NULLIF(trim(settings::jsonb ->> 'workflow_graph_tenant_id'), '') "
        f"FROM {_table()} WHERE id = %s::uuid LIMIT 1"
    )
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (needle,))
            row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0]).strip() or None


class TenantsDbRepository:
    """Thin class wrapper for dependency injection / tests."""

    def find_tenant_id_by_email_webhook_name(self, webhook_name: str) -> Optional[str]:
        return find_tenant_id_by_settings_email_webhook_name(webhook_name)

    def get_settings_workflow_graph_tenant_id(self, tenant_uuid: str) -> Optional[str]:
        return get_settings_workflow_graph_tenant_id(tenant_uuid)
