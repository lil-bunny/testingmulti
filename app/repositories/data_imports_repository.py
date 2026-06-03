"""Insert rows into ``data_imports`` (JSONB raw payloads)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import execute_scalar, fetchone_dict, jsonb_param, parse_json


class DataImportsRepository:
    TABLE_NAME = "data_imports"

    def __init__(self, session: Session) -> None:
        self._session = session

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

        row_id = execute_scalar(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                data_type,
                source_type,
                file_name,
                raw_data
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:data_type AS data_import_data_type),
                CAST(:source_type AS data_import_source_type),
                :file_name,
                CAST(:raw_data AS jsonb)
            )
            RETURNING id::text
            """,
            {
                "tenant_id": tid,
                "data_type": dt,
                "source_type": st,
                "file_name": file_name,
                "raw_data": jsonb_param(raw_data),
            },
        )
        if not row_id:
            raise RuntimeError("data_imports insert returned no id")
        return str(row_id)

    def fetch_raw_data_by_id(
        self, *, tenant_id: str, data_import_id: str
    ) -> dict[str, Any] | None:
        tid = tenant_id.strip()
        did = data_import_id.strip()
        if not tid or not did:
            raise ValueError("tenant_id and data_import_id are required")

        row = fetchone_dict(
            self._session,
            f"""
            SELECT raw_data
            FROM {self.TABLE_NAME}
            WHERE id = CAST(:data_import_id AS uuid)
              AND tenant_id = CAST(:tenant_id AS uuid)
            """,
            {"data_import_id": did, "tenant_id": tid},
        )
        if not row or row.get("raw_data") is None:
            return None
        raw = row["raw_data"]
        if isinstance(raw, dict):
            return raw
        parsed = parse_json(raw)
        if parsed:
            return parsed
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

        row_id = execute_scalar(
            self._session,
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND raw_data->'source'->>'email_id' = :email_id
              AND raw_data->'source'->>'attachment_id' = :attachment_id
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"tenant_id": tid, "email_id": eid, "attachment_id": aid},
        )
        if not row_id:
            return None
        return str(row_id)

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

        row_id = execute_scalar(
            self._session,
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND data_type = CAST(:data_type AS data_import_data_type)
              AND file_name = :file_name
            ORDER BY updated_at DESC NULLS LAST, created_at DESC
            LIMIT 1
            """,
            {"tenant_id": tid, "data_type": dt, "file_name": fn},
        )
        if not row_id:
            return None
        return str(row_id)

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

        if file_name is not None:
            sql = f"""
                UPDATE {self.TABLE_NAME}
                SET raw_data = CAST(:raw_data AS jsonb),
                    file_name = :file_name,
                    updated_at = NOW()
                WHERE id = CAST(:data_import_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """
            params: dict[str, Any] = {
                "raw_data": jsonb_param(raw_data),
                "file_name": file_name,
                "data_import_id": did,
                "tenant_id": tid,
            }
        else:
            sql = f"""
                UPDATE {self.TABLE_NAME}
                SET raw_data = CAST(:raw_data AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:data_import_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
            """
            params = {
                "raw_data": jsonb_param(raw_data),
                "data_import_id": did,
                "tenant_id": tid,
            }

        result = self._session.execute(text(sql), params)
        if result.rowcount < 1:
            raise RuntimeError(
                f"data_imports update affected no rows id={did} tenant_id={tid}"
            )
