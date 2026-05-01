"""Postgres persistence for `documents` (POD / ratecon artifacts).

Mirrors the pattern in ``app.tools.workflow_correlation``: optional runtime
``CREATE TABLE IF NOT EXISTS`` for dev, configurable table name via settings.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import psycopg

from app.core.config import settings
from app.models.document import DocumentType

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
                    url TEXT,
                    email_id TEXT,
                    attachment_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS email_id TEXT"
            )
            cur.execute(
                f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS attachment_id TEXT"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{t}_shipment_id ON {t}(shipment_id)"
            )
            cur.execute(f"CREATE INDEX IF NOT EXISTS idx_{t}_type ON {t}(type)")
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{t}_unipile_source
                ON {t}(email_id, attachment_id)
                WHERE email_id IS NOT NULL AND attachment_id IS NOT NULL
                """
            )
        conn.commit()
        _PG_READY = True
        logger.info("documents: ensured table %s exists", t)
    finally:
        conn.close()


def insert_document(
    doc_type: DocumentType,
    shipment_id: str,
    url: str,
    *,
    email_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Insert one ``documents`` row. Returns ``{stored, id?, type?, created_at?, error?}``."""

    if not shipment_id or not url:
        logger.warning(
            "insert_document: skip persist (type=%s shipment_id=%r url_set=%s)",
            doc_type.value,
            shipment_id,
            bool(url),
        )
        return {"stored": False, "id": None, "error": "missing_shipment_id_or_url"}

    _ensure_pg_table()
    doc_id = str(uuid.uuid4())
    t = _table_name()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {t} (id, type, shipment_id, url, email_id, attachment_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, type, created_at
                """,
                (doc_id, doc_type.value, shipment_id, url, email_id, attachment_id),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return {"stored": False, "id": None, "error": "insert_returned_no_row"}
        logger.info(
            "insert_document: stored id=%s type=%s shipment_id=%s",
            row[0],
            row[1],
            shipment_id,
        )
        return {"stored": True, "id": row[0], "type": str(row[1]), "created_at": row[2]}
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

    ``doc_type`` is a :class:`~app.models.document.DocumentType` value.
    Rate confirmation artifacts are expected at S3 paths whose basename is
    ``ratecon_{shipmentId}.pdf`` (with the same path-segment sanitization used
    elsewhere); the stored ``url`` column is the source of truth for downloads.

    Returns ``{found, id, url, shipment_id, type, created_at, error}``.
    """

    sid = (shipment_id or "").strip()
    if not sid:
        return {
            "found": False,
            "id": None,
            "url": None,
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
                SELECT id, url, type, shipment_id, created_at
                FROM {t}
                WHERE shipment_id = %s AND type = %s
                  AND url IS NOT NULL AND BTRIM(url) <> ''
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
                "url": None,
                "shipment_id": sid,
                "type": doc_type.value,
                "created_at": None,
                "error": None,
            }
        return {
            "found": True,
            "id": row[0],
            "url": row[1],
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
            "url": None,
            "shipment_id": sid,
            "type": doc_type.value,
            "created_at": None,
            "error": str(exc),
        }
    finally:
        conn.close()

