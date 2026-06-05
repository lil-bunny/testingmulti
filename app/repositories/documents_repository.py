"""Read/write ``documents`` (POD / ratecon S3 artifact metadata)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchone_dict

_NONEMPTY_OBJECT_KEY = """
    AND object_key IS NOT NULL AND BTRIM(object_key) <> ''
"""


class DocumentsRepository:
    TABLE_NAME = "documents"

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_by_object_key(
        self,
        *,
        id: str,
        doc_type: str,
        shipment_id: str,
        object_key: str,
    ) -> dict[str, Any] | None:
        """Insert or update by ``object_key``; return row fields from ``RETURNING``."""
        return fetchone_dict(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (id, type, shipment_id, object_key)
            VALUES (:id, :type, :shipment_id, :object_key)
            ON CONFLICT (object_key) DO UPDATE
            SET
                type = EXCLUDED.type,
                shipment_id = EXCLUDED.shipment_id
            RETURNING id, type, shipment_id, object_key, created_at
            """,
            {
                "id": id,
                "type": doc_type,
                "shipment_id": shipment_id,
                "object_key": object_key,
            },
        )

    def find_latest_by_shipment_and_type(
        self,
        *,
        shipment_id: str,
        doc_type: str,
    ) -> dict[str, Any] | None:
        """Latest row for ``shipment_id`` + ``type`` with a non-empty ``object_key``."""
        return fetchone_dict(
            self._session,
            f"""
            SELECT id, object_key, type, shipment_id, created_at
            FROM {self.TABLE_NAME}
            WHERE shipment_id = :shipment_id AND type = :type
              {_NONEMPTY_OBJECT_KEY}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"shipment_id": shipment_id, "type": doc_type},
        )
