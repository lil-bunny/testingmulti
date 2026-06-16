"""Postgres ``tenants`` table lookups (app-level tenant UUID ``id``, JSON ``settings``)."""

from __future__ import annotations

import uuid as uuid_std
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy.orm import Session

from app.core.db import db_scope, execute_scalar, fetchall_dicts, fetchone_dict, parse_json
from app.core.logger import get_logger

logger = get_logger(__name__)

_WHERE_SLUG_CI = """
    WHERE lower(trim(slug)) = lower(:slug)
"""


@dataclass(frozen=True)
class InboundRoutingTenantMatch:
    """Result of matching normalized recipient emails to ``inbound_routing_emails``."""

    tenant_id: str | None
    slug: str | None
    match_count: int


class TenantsDbRepository:
    """Tenant row lookups by slug, webhook name, and UUID."""

    TABLE_NAME = "tenants"

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
            FROM {self.TABLE_NAME}
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

    def find_by_inbound_routing_emails(self, emails: list[str]) -> InboundRoutingTenantMatch:
        """
        Match pre-normalized recipient emails against ``settings.inbound_routing_emails``.

        ``emails`` must come from ``extract_recipient_emails`` or validated tenant settings
        (strip, lowercase, deduped, valid ``@``). Returns up to three matching rows.
        """
        if not emails:
            return InboundRoutingTenantMatch(None, None, 0)

        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT id::text AS id, NULLIF(trim(slug), '') AS slug
            FROM {self.TABLE_NAME}
            WHERE settings IS NOT NULL
              AND jsonb_exists_any(settings->'inbound_routing_emails', CAST(:emails_lower AS text[]))
            ORDER BY id
            LIMIT 3
            """,
            {"emails_lower": emails},
        )
        if not rows:
            return InboundRoutingTenantMatch(None, None, 0)

        match_count = len(rows)
        if match_count > 1:
            logger.warning(
                "tenants lookup: multiple rows match inbound_routing_emails (%s ids)",
                match_count,
            )
        first = rows[0]
        slug = first.get("slug")
        return InboundRoutingTenantMatch(
            str(first["id"]),
            str(slug).strip() if slug else None,
            match_count,
        )

    def fetch_tenant_settings_by_slug(self, slug: str) -> dict[str, Any] | None:
        """Return ``tenants.settings`` JSON for ``slug`` (case-insensitive), or ``None``."""

        needle = slug.strip()
        if not needle:
            return None

        row = fetchone_dict(
            self._session,
            f"""
            SELECT settings
            FROM {self.TABLE_NAME}
            {_WHERE_SLUG_CI}
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
            FROM {self.TABLE_NAME}
            {_WHERE_SLUG_CI}
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
            FROM {self.TABLE_NAME}
            WHERE id = CAST(:tenant_uuid AS uuid)
            LIMIT 1
            """,
            {"tenant_uuid": needle},
        )
        if slug is None:
            return None
        return str(slug).strip() or None


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
