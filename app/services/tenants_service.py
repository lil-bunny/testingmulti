"""Read-only access to ``tenants`` (slug + settings) for workflow nodes."""

from __future__ import annotations

import json
from typing import Any

import psycopg

from app.core.config import settings


class TenantsService:
    """Mirror style of ``WorkflowLifecycleService`` / ``WorkflowRunsService`` (psycopg + ``DATABASE_URL``)."""

    TABLE_NAME = "tenants"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        """
        Return tenant row keyed by ``slug`` (matches ``TENANT_CONFIGS`` keys), or None.

        ``settings`` is parsed JSON (empty dict if null).
        ``id`` is the UUID string used for ``tenders.tenant_id`` FK joins.
        """
        s = self._clean(slug)
        if not s:
            return None
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, name, slug, settings
                    FROM {self.TABLE_NAME}
                    WHERE slug = %s
                    LIMIT 1
                    """,
                    (s,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                raw_settings = row[3]
                if isinstance(raw_settings, dict):
                    parsed: dict[str, Any] = raw_settings
                elif raw_settings in (None, ""):
                    parsed = {}
                else:
                    parsed = json.loads(raw_settings)
                return {
                    "id": str(row[0]),
                    "name": row[1] or "",
                    "slug": row[2] or "",
                    "settings": parsed,
                }
        finally:
            conn.close()
