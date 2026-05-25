"""Read ``pack_codes`` for tenant-scoped ingest resolution."""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings


class PackCodesRepository:
    TABLE_NAME = "pack_codes"

    @staticmethod
    def _normalize_pack_code(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def active_pack_code_id_index(self, *, tenant_id: str) -> dict[str, str]:
        """
        Map trimmed ``pack_codes.pack_code`` text → ``pack_codes.id`` for active rows.

        Lookup at ingest is exact match on trimmed text (no numeric normalization).
        """
        tid = str(tenant_id).strip()
        if not tid:
            return {}

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id::text, pack_code
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid
                      AND is_active IS TRUE
                    """,
                    (tid,),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        index: dict[str, str] = {}
        for pid, code in rows:
            key = self._normalize_pack_code(code)
            if key and pid:
                index[key] = str(pid)
        return index
