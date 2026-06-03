"""Postgres ``tenants`` table lookups (app-level tenant UUID ``id``, JSON ``settings``)."""

from __future__ import annotations

import uuid as uuid_std
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import db_scope, execute_scalar, fetchall_dicts, fetchone_dict, parse_json
from app.core.logger import get_logger

logger = get_logger(__name__)


def _table() -> str:
    t = settings.TENANTS_TABLE.strip()
    return t if t else "tenants"


class TenantsDbRepository:
    """Tenant row lookups by slug, webhook name, and UUID."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Return ``{id, name, slug, settings}`` for a tenant slug, or ``None``."""
        s = self._clean(slug)
        if not s:
            return None
        row = fetchone_dict(
            self._session,
            f"""
            SELECT id::text AS id, name, slug, settings
            FROM {_table()}
            WHERE slug = :slug
            LIMIT 1
            """,
            {"slug": s},
            json_keys=frozenset({"settings"}),
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "name": row.get("name") or "",
            "slug": row.get("slug") or "",
            "settings": parse_json(row.get("settings")),
        }

    def find_tenant_id_by_email_webhook_name(self, webhook_name: str) -> Optional[str]:
        """
        Return ``tenants.id`` (UUID string) where ``settings`` JSON contains
        ``email_webhook_name`` equal to ``webhook_name`` (exact match).

        Ignores whitespace-only ``webhook_name``. If multiple rows match, logs and returns the
        first by ``id``.
        """
        needle = webhook_name.strip()
        if not needle:
            return None

        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT id::text AS id
            FROM {_table()}
            WHERE settings IS NOT NULL
              AND (settings::jsonb ->> 'email_webhook_name') = :webhook_name
            ORDER BY id
            LIMIT 3
            """,
            {"webhook_name": needle},
        )
        if not rows:
            return None
        if len(rows) > 1:
            logger.warning(
                "tenants lookup: multiple rows match email_webhook_name=%r (%s ids); "
                "using first",
                needle,
                len(rows),
            )
        return str(rows[0]["id"])

    def fetch_tenant_settings_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Return ``tenants.settings`` JSON for ``slug`` (case-insensitive), or ``None``."""

        needle = slug.strip()
        if not needle:
            return None

        row = fetchone_dict(
            self._session,
            f"""
            SELECT settings
            FROM {_table()}
            WHERE lower(trim(slug)) = lower(:slug)
            ORDER BY id
            LIMIT 1
            """,
            {"slug": needle},
        )
        if not row or row.get("settings") is None:
            return None
        raw = row["settings"]
        if isinstance(raw, dict):
            return raw
        if hasattr(raw, "items"):
            return dict(raw)
        return None

    def find_tenant_uuid_by_slug(self, slug: str) -> Optional[str]:
        """Return ``tenants.id`` where ``slug`` matches (case-insensitive trim)."""

        needle = slug.strip()
        if not needle:
            return None

        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT id::text AS id
            FROM {_table()}
            WHERE lower(trim(slug)) = lower(:slug)
            ORDER BY id
            LIMIT 3
            """,
            {"slug": needle},
        )
        if not rows:
            return None
        return str(rows[0]["id"])

    def resolve_graph_tenant_to_uuid(self, tenant_id: str | None) -> Optional[str]:
        """Map graph/config key or UUID string to ``tenants.id`` (UUID hex)."""

        cleaned = (tenant_id or "").strip()
        if not cleaned:
            return None
        try:
            uuid_std.UUID(cleaned)
            return cleaned
        except (ValueError, AttributeError):
            return self.find_tenant_uuid_by_slug(cleaned)

    def get_slug_for_tenant_uuid(self, tenant_uuid: str) -> Optional[str]:
        """
        Return ``tenants.slug`` for row ``id = tenant_uuid``.

        Blank slug values return ``None``. Missing row yields ``None``.
        """
        needle = tenant_uuid.strip()
        if not needle:
            return None

        slug = execute_scalar(
            self._session,
            f"""
            SELECT NULLIF(trim(slug), '')
            FROM {_table()}
            WHERE id = CAST(:tenant_uuid AS uuid)
            LIMIT 1
            """,
            {"tenant_uuid": needle},
        )
        if slug is None:
            return None
        return str(slug).strip() or None


def find_tenant_id_by_settings_email_webhook_name(webhook_name: str) -> Optional[str]:
    with db_scope() as repos:
        return repos.tenants.find_tenant_id_by_email_webhook_name(webhook_name)


def fetch_tenant_settings_by_slug(slug: str) -> dict[str, Any] | None:
    with db_scope() as repos:
        return repos.tenants.fetch_tenant_settings_by_slug(slug)


def find_tenant_uuid_by_slug(slug: str) -> Optional[str]:
    with db_scope() as repos:
        return repos.tenants.find_tenant_uuid_by_slug(slug)


def resolve_graph_tenant_to_uuid(tenant_id: str | None) -> Optional[str]:
    with db_scope() as repos:
        return repos.tenants.resolve_graph_tenant_to_uuid(tenant_id)


def get_slug_for_tenant_uuid(tenant_uuid: str) -> Optional[str]:
    with db_scope() as repos:
        return repos.tenants.get_slug_for_tenant_uuid(tenant_uuid)
