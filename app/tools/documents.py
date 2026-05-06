"""Postgres persistence for `documents` (POD / ratecon artifacts).

Mirrors the pattern in ``app.tools.workflow_correlation``: optional runtime
``CREATE TABLE IF NOT EXISTS`` for dev, configurable table name via settings.

S3 alignment: ``S3Bucket.upload_file`` returns ``object_key``; this module stores
keys on each row for idempotent upserts by ``object_key``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import psycopg

from app.core.config import settings
from app.models.document import DocumentType
from app.services.s3bucket_service import normalize_object_key

logger = logging.getLogger(__name__)

_PG_READY = False

_DOC_TYPE_SQL_IN = ", ".join(f"'{m.value}'" for m in DocumentType)


def _try_pg_connection():
    return psycopg.connect(settings.DATABASE_URL)


def _table_name() -> str:
    return settings.DOCUMENTS_TABLE


def _ensure_pg_table() -> None:
    global _PG_READY
    if _PG_READY:
        return
    t = _table_name()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {t} (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL
                        CHECK (type IN ({_DOC_TYPE_SQL_IN})),
                    shipment_id TEXT NOT NULL,
                    object_key TEXT NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{t}_shipment_id ON {t}(shipment_id)"
            )
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_type ON {t}(type)")
            cur.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS uq_{t}_object_key ON {t}(object_key)"
            )
        conn.commit()
        _PG_READY = True
        logger.info("documents: ensured table %s exists", t)
    finally:
        conn.close()


def insert_document(
    doc_type: DocumentType,
    shipment_id: str,
    object_key: str,
    *,
    email_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Upsert one ``documents`` row by ``object_key``.

    Returns ``{stored, id?, type?, shipment_id?, object_key?, created_at?, error?}``.

    ``object_key`` is the S3 object key (e.g. ``freightx/pod_attachments/...``), stored in the ``object_key`` column.
    """

    if not shipment_id or not object_key:
        logger.warning(
            "insert_document: skip persist (type=%s shipment_id=%r object_key_set=%s)",
            doc_type.value,
            shipment_id,
            bool(object_key),
        )
        return {"stored": False, "id": None, "error": "missing_shipment_id_or_object_key"}

    try:
        key = normalize_object_key(object_key)
    except ValueError as exc:
        return {"stored": False, "id": None, "error": str(exc)}
    if not key:
        return {"stored": False, "id": None, "error": "empty_object_key"}

    _ensure_pg_table()
    doc_id = str(uuid.uuid4())
    t = _table_name()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {t} (id, type, shipment_id, object_key)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (object_key) DO UPDATE
                SET
                    type = documents.type,
                    shipment_id = documents.shipment_id
                RETURNING id, type, shipment_id, object_key, created_at
                """,
                (doc_id, doc_type.value, shipment_id, key),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return {"stored": False, "id": None, "error": "insert_returned_no_row"}
        logger.info(
            "insert_document: stored id=%s type=%s shipment_id=%s object_key=%s",
            row[0],
            row[1],
            row[2],
            row[3],
        )
        return {
            "stored": True,
            "id": row[0],
            "type": str(row[1]),
            "shipment_id": row[2],
            "object_key": row[3],
            "created_at": row[4],
        }
    except Exception as exc:
        logger.exception(
            "insert_document: failed type=%s shipment_id=%s",
            doc_type.value,
            shipment_id,
        )
        return {"stored": False, "id": None, "error": str(exc)}
    finally:
        conn.close()


def read_document(shipment_id: str, doc_type: DocumentType) -> dict[str, Any]:
    """
    Load the latest ``documents`` row for ``shipment_id`` and ``doc_type``.

    The ``object_key`` column stores the S3 object key.

    Rate confirmation artifacts use basename ``ratecon_{shipmentId}.pdf`` (sanitized).

    Returns ``{found, id, object_key, shipment_id, type, created_at, error}``.
    """

    sid = (shipment_id or "").strip()
    if not sid:
        return {
            "found": False,
            "id": None,
            "object_key": None,
            "shipment_id": shipment_id,
            "type": doc_type.value,
            "created_at": None,
            "error": "missing_shipment_id",
        }

    _ensure_pg_table()
    t = _table_name()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, object_key, type, shipment_id, created_at
                FROM {t}
                WHERE shipment_id = %s AND type = %s
                  AND object_key IS NOT NULL AND BTRIM(object_key) <> ''
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (sid, doc_type.value),
            )
            row = cur.fetchone()
        if not row:
            logger.info(
                "read_document: no row for shipment_id=%s type=%s",
                sid,
                doc_type.value,
            )
            return {
                "found": False,
                "id": None,
                "object_key": None,
                "shipment_id": sid,
                "type": doc_type.value,
                "created_at": None,
                "error": None,
            }
        return {
            "found": True,
            "id": row[0],
            "object_key": row[1],
            "type": str(row[2]),
            "shipment_id": row[3],
            "created_at": row[4],
            "error": None,
        }
    except Exception as exc:
        logger.exception(
            "read_document: query failed shipment_id=%s type=%s",
            sid,
            doc_type.value,
        )
        return {
            "found": False,
            "id": None,
            "object_key": None,
            "shipment_id": sid,
            "type": doc_type.value,
            "created_at": None,
            "error": str(exc),
        }
    finally:
        conn.close()

