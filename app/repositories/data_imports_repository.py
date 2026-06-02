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

    def find_id_by_email_attachment_source(
        self,
        *,
        tenant_id: str,
        email_id: str,
        attachment_id: str,
    ) -> str | None:
        tid = tenant_id.strip()
        eid = email_id.strip()
        aid = attachment_id.strip()
        if not tid or not eid or not aid:
            return None

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id::text
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid
                      AND raw_data->'source'->>'email_id' = %s
                      AND raw_data->'source'->>'attachment_id' = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (tid, eid, aid),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if not row or not row[0]:
            return None
        return str(row[0])

    def find_id_by_tenant_data_type_and_file_name(
        self,
        *,
        tenant_id: str,
        data_type: str,
        file_name: str,
    ) -> str | None:
        tid = tenant_id.strip()
        dt = data_type.strip()
        fn = file_name.strip()
        if not tid or not dt or not fn:
            return None

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id::text
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid
                      AND data_type = %s::data_import_data_type
                      AND file_name = %s
                    ORDER BY updated_at DESC NULLS LAST, created_at DESC
                    LIMIT 1
                    """,
                    (tid, dt, fn),
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if not row or not row[0]:
            return None
        return str(row[0])

    def update_raw_data(
        self,
        *,
        tenant_id: str,
        data_import_id: str,
        raw_data: dict[str, Any],
        file_name: str | None = None,
    ) -> None:
        tid = tenant_id.strip()
        did = data_import_id.strip()
        if not tid or not did:
            raise ValueError("tenant_id and data_import_id are required")

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                if file_name is not None:
                    cur.execute(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET raw_data = %s,
                            file_name = %s,
                            updated_at = NOW()
                        WHERE id = %s::uuid AND tenant_id = %s::uuid
                        """,
                        (Json(raw_data), file_name, did, tid),
                    )
                else:
                    cur.execute(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET raw_data = %s,
                            updated_at = NOW()
                        WHERE id = %s::uuid AND tenant_id = %s::uuid
                        """,
                        (Json(raw_data), did, tid),
                    )
                if cur.rowcount < 1:
                    raise RuntimeError(
                        f"data_imports update affected no rows id={did} tenant_id={tid}"
                    )
            conn.commit()
        finally:
            conn.close()
