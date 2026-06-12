"""Read/write ``documents`` (POD / ratecon S3 artifact metadata)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchone_dict

_NONEMPTY_STORAGE_KEY = """
    AND storage_key IS NOT NULL AND BTRIM(storage_key) <> ''
"""


class DocumentsRepository:
    TABLE_NAME = "documents"

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_by_storage_key(
        self,
        *,
        id: str,
        doc_type: str,
        shipment_id: str | None,
        storage_key: str,
    ) -> dict[str, Any] | None:
        """Insert or update by ``storage_key``; return row fields from ``RETURNING``."""
        sql = f"""
            INSERT INTO {self.TABLE_NAME} (id, type, shipment_id, storage_key)
            VALUES (CAST(:id AS uuid), :type, CAST(:shipment_id AS uuid), :storage_key)
            ON CONFLICT (storage_key) DO UPDATE
            SET
                type = EXCLUDED.type,
                shipment_id = EXCLUDED.shipment_id
            RETURNING id, type, shipment_id, storage_key, created_at
            """
        params = {
            "id": id,
            "type": doc_type,
            "shipment_id": shipment_id,
            "storage_key": storage_key,
        }
        return fetchone_dict(self._session, sql, params)

    def find_latest_by_shipment_and_type(
        self,
        *,
        shipment_id: str,
        doc_type: str,
    ) -> dict[str, Any] | None:
        """Latest row for ``shipment_id`` + ``type`` with a non-empty ``storage_key``."""
        return fetchone_dict(
            self._session,
            f"""
            SELECT id, storage_key, type, shipment_id, created_at
            FROM {self.TABLE_NAME}
            WHERE shipment_id = :shipment_id AND type = :type
              {_NONEMPTY_STORAGE_KEY}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"shipment_id": shipment_id, "type": doc_type},
        )
