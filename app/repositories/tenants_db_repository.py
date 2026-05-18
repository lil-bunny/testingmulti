"""Postgres ``tenants`` table lookups (app-level tenant UUID ``id``, JSON ``settings``)."""

from __future__ import annotations

import uuid as uuid_std
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


def find_tenant_uuid_by_slug(slug: str) -> Optional[str]:
    """Return ``tenants.id`` where ``slug`` matches (case-insensitive trim)."""

    needle = slug.strip()
    if not needle:
        return None
    sql = (
        f"SELECT id::text FROM {_table()} "
        "WHERE lower(trim(slug)) = lower(%s) "
        "ORDER BY id LIMIT 3"
    )
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (needle,))
            rows = cur.fetchall()
    if not rows:
        return None
    return str(rows[0][0])


def resolve_graph_tenant_to_uuid(tenant_id: str | None) -> Optional[str]:
    """Map graph/config key or UUID string to ``tenants.id`` (UUID hex)."""

    cleaned = (tenant_id or "").strip()
    if not cleaned:
        return None
    try:
        uuid_std.UUID(cleaned)
        return cleaned
    except (ValueError, AttributeError):
        return find_tenant_uuid_by_slug(cleaned)


def get_slug_for_tenant_uuid(tenant_uuid: str) -> Optional[str]:
    """
    Return ``tenants.slug`` for row ``id = tenant_uuid``.

    Blank slug values return ``None``. Missing row yields ``None``.
    """
    needle = tenant_uuid.strip()
    if not needle:
        return None
    sql = (
        f"SELECT NULLIF(trim(slug), '') "
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

    def find_tenant_uuid_by_slug(self, slug: str) -> Optional[str]:
        return find_tenant_uuid_by_slug(slug)

    def resolve_graph_tenant_to_uuid(self, tenant_id: str | None) -> Optional[str]:
        return resolve_graph_tenant_to_uuid(tenant_id)

    def get_slug_for_tenant_uuid(self, tenant_uuid: str) -> Optional[str]:
        return get_slug_for_tenant_uuid(tenant_uuid)
