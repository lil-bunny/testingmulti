"""Postgres ``tenants`` table lookups (app-level tenant UUID ``id``, JSON ``config``)."""

from __future__ import annotations

from typing import Optional

import psycopg

from app.core.config import settings


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


def _table() -> str:
    t = settings.TENANTS_TABLE.strip()
    return t if t else "tenants"


def find_tenant_id_by_config_email_webhook_name(webhook_name: str) -> Optional[str]:
    """
    Return ``tenants.id`` (UUID string) where ``config`` JSON contains
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
        "WHERE config IS NOT NULL "
        "AND (config::jsonb ->> 'email_webhook_name') = %s "
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


class TenantsDbRepository:
    """Thin class wrapper for dependency injection / tests."""

    def find_tenant_id_by_email_webhook_name(self, webhook_name: str) -> Optional[str]:
        return find_tenant_id_by_config_email_webhook_name(webhook_name)
