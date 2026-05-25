"""Insert rows into ``data_imports`` (JSONB raw payloads)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


class DataImportsRepository:
    TABLE_NAME = "data_imports"

    def insert(
        self,
        *,
        tenant_id: str,
        data_type: str,
        source_type: str,
        file_name: str | None,
        raw_data: dict[str, Any],
    ) -> str:
        tid = tenant_id.strip()
        dt = data_type.strip()
        st = source_type.strip()
        if not tid or not dt or not st:
            raise ValueError("tenant_id, data_type, and source_type are required")

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        tenant_id,
                        data_type,
                        source_type,
                        file_name,
                        raw_data
                    )
                    VALUES (
                        %s::uuid,
                        %s::data_import_data_type,
                        %s::data_import_source_type,
                        %s,
                        %s
                    )
                    RETURNING id::text
                    """,
                    (tid, dt, st, file_name, Json(raw_data)),
                )
                row = cur.fetchone()
            conn.commit()
        finally:
            conn.close()

        if not row or not row[0]:
            raise RuntimeError("data_imports insert returned no id")
        return str(row[0])

    def fetch_raw_data_by_id(
        self, *, tenant_id: str, data_import_id: str
    ) -> dict[str, Any] | None:
        tid = tenant_id.strip()
        did = data_import_id.strip()
        if not tid or not did:
            raise ValueError("tenant_id and data_import_id are required")

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT raw_data
                    FROM {self.TABLE_NAME}
                    WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (did, tid),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if not row or row[0] is None:
            return None
        raw = row[0]
        if isinstance(raw, dict):
            return raw
        raise TypeError("data_imports.raw_data must decode to a dict")
