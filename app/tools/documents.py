"""Postgres persistence for `documents` (POD / ratecon artifacts).

S3 alignment: ``S3Bucket.upload_file`` returns ``object_key``; this module stores
keys on each row as ``storage_key``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction
from app.models.document import DocumentType
from app.services.s3bucket_service import normalize_object_key
from app.workflows.shipment_resolver import resolve_shipments_row_id_for_db

logger = logging.getLogger(__name__)


def _uuid_or_none(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def insert_document(
    doc_type: DocumentType,
    storage_key: str,
    *,
    shipments_row_id: str | None = None,
    email_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
) -> dict[str, Any]:
    """Upsert one ``documents`` row by ``storage_key``.

    Returns ``{stored, id?, type?, shipment_id?, storage_key?, created_at?, error?}``.

    ``storage_key`` is the S3 object key (e.g. ``freightx/pod_attachments/...``).
    ``shipments_row_id`` is ``shipments.id`` (nullable FK); omit or pass ``None`` when unknown.
    """

    if not storage_key:
        logger.warning(
            "insert_document: skip persist (type=%s shipments_row_id=%r storage_key_set=%s)",
            doc_type.value,
            shipments_row_id,
            bool(storage_key),
        )
        return {"stored": False, "id": None, "error": "missing_storage_key"}

    try:
        key = normalize_object_key(storage_key)
    except ValueError as exc:
        return {"stored": False, "id": None, "error": str(exc)}
    if not key:
        return {"stored": False, "id": None, "error": "empty_storage_key"}

    doc_id = str(uuid.uuid4())
    row_shipment_id = _uuid_or_none(shipments_row_id)
    if shipments_row_id and not row_shipment_id:
        logger.warning(
            "insert_document: ignoring non-uuid shipments_row_id=%r (type=%s)",
            shipments_row_id,
            doc_type.value,
        )

    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                row = repos.documents.upsert_by_storage_key(
                    id=doc_id,
                    doc_type=doc_type.value,
                    shipment_id=row_shipment_id,
                    storage_key=key,
                )
        if not row:
            return {"stored": False, "id": None, "error": "insert_returned_no_row"}
        return {
            "stored": True,
            "id": str(row["id"]),
            "type": str(row["type"]),
            "shipment_id": row["shipment_id"],
            "storage_key": row["storage_key"],
            "created_at": row["created_at"],
        }
    except Exception as exc:
        logger.exception(
            "insert_document: failed type=%s shipments_row_id=%s",
            doc_type.value,
            row_shipment_id,
        )
        return {"stored": False, "id": None, "error": str(exc)}


def resolve_merged_pod_object_key(data: dict) -> tuple[str | None, dict[str, Any]]:
    """Resolve merged POD S3 key from workflow state; fallback to latest ``pod_merged_final`` row."""
    refs = data.get("pod_object_keys") or []
    if isinstance(refs, list):
        for u in refs:
            if u and str(u).strip():
                return str(u).strip(), {"source": "state"}
    merged = data.get("pod_merged_pdf_object_key")
    if merged and str(merged).strip():
        return str(merged).strip(), {"source": "state"}
    shipments_row_id = resolve_shipments_row_id_for_db(data)
    if shipments_row_id:
        doc = read_document(shipments_row_id, DocumentType.POD_MERGED_FINAL)
        if doc.get("error"):
            return None, {"source": "documents", "error": doc["error"]}
        if doc.get("found") and doc.get("storage_key"):
            return doc["storage_key"], {"source": "documents", "document_id": doc.get("id")}
    return None, {}


def read_document(shipments_row_id: str | None, doc_type: DocumentType) -> dict[str, Any]:
    """
    Load the latest ``documents`` row for ``shipments_row_id`` and ``doc_type``.

    Returns ``{found, id, storage_key, shipment_id, type, created_at, error}``.
    """

    sid = _uuid_or_none(shipments_row_id)
    if shipments_row_id and not sid:
        logger.warning(
            "read_document: ignoring non-uuid shipments_row_id=%r type=%s",
            shipments_row_id,
            doc_type.value,
        )
    if not sid:
        return {
            "found": False,
            "id": None,
            "storage_key": None,
            "shipment_id": shipments_row_id,
            "type": doc_type.value,
            "created_at": None,
            "error": "missing_shipments_row_id",
        }

    try:
        with db_scope() as repos:
            row = repos.documents.find_latest_by_shipment_and_type(
                shipment_id=sid,
                doc_type=doc_type.value,
            )
        if not row:
            logger.info(
                "read_document: no row for shipments_row_id=%s type=%s",
                sid,
                doc_type.value,
            )
            return {
                "found": False,
                "id": None,
                "storage_key": None,
                "shipment_id": sid,
                "type": doc_type.value,
                "created_at": None,
                "error": None,
            }
        return {
            "found": True,
            "id": str(row["id"]),
            "storage_key": row["storage_key"],
            "type": str(row["type"]),
            "shipment_id": row["shipment_id"],
            "created_at": row["created_at"],
            "error": None,
        }
    except Exception as exc:
        logger.exception(
            "read_document: query failed shipments_row_id=%s type=%s",
            sid,
            doc_type.value,
        )
        return {
            "found": False,
            "id": None,
            "storage_key": None,
            "shipment_id": sid,
            "type": doc_type.value,
            "created_at": None,
            "error": str(exc),
        }
