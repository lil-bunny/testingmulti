"""Postgres persistence for `documents` (POD / ratecon artifacts).

S3 alignment: ``S3Bucket.upload_file`` returns ``object_key``; this module stores
keys on each row for idempotent upserts by ``object_key``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction, fetchone_dict
from app.models.document import DocumentType
from app.services.s3bucket_service import normalize_object_key

logger = logging.getLogger(__name__)

TABLE_NAME = "documents"


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

    ``object_key`` is the S3 object key (e.g. ``freightx/{BUCKET_POD_ATTACHMENTS_FOLDER}/...``), stored in the ``object_key`` column.
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

    doc_id = str(uuid.uuid4())
    sql = f"""
        INSERT INTO {TABLE_NAME} (id, type, shipment_id, object_key)
        VALUES (:id, :type, :shipment_id, :object_key)
        ON CONFLICT (object_key) DO UPDATE
        SET
            type = EXCLUDED.type,
            shipment_id = EXCLUDED.shipment_id
        RETURNING id, type, shipment_id, object_key, created_at
    """
    params = {
        "id": doc_id,
        "type": doc_type.value,
        "shipment_id": shipment_id,
        "object_key": key,
    }

    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                row = fetchone_dict(repos.session, sql, params)
        if not row:
            return {"stored": False, "id": None, "error": "insert_returned_no_row"}
        logger.info(
            "insert_document: stored id=%s type=%s shipment_id=%s object_key=%s",
            row["id"],
            row["type"],
            row["shipment_id"],
            row["object_key"],
        )
        return {
            "stored": True,
            "id": row["id"],
            "type": str(row["type"]),
            "shipment_id": row["shipment_id"],
            "object_key": row["object_key"],
            "created_at": row["created_at"],
        }
    except Exception as exc:
        logger.exception(
            "insert_document: failed type=%s shipment_id=%s",
            doc_type.value,
            shipment_id,
        )
        return {"stored": False, "id": None, "error": str(exc)}


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

    sql = f"""
        SELECT id, object_key, type, shipment_id, created_at
        FROM {TABLE_NAME}
        WHERE shipment_id = :shipment_id AND type = :type
          AND object_key IS NOT NULL AND BTRIM(object_key) <> ''
        ORDER BY created_at DESC
        LIMIT 1
    """
    params = {"shipment_id": sid, "type": doc_type.value}

    try:
        with db_scope() as repos:
            row = fetchone_dict(repos.session, sql, params)
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
            "id": row["id"],
            "object_key": row["object_key"],
            "type": str(row["type"]),
            "shipment_id": row["shipment_id"],
            "created_at": row["created_at"],
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
