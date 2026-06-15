"""Postgres persistence for ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction
from app.models.document_analysis import DocumentAnalysisType
from app.tools.documents import _uuid_or_none

logger = logging.getLogger(__name__)


def upsert_document_analysis(
    shipments_row_id: str | None,
    analysis_type: DocumentAnalysisType,
    *,
    results: dict[str, Any],
    confidence_score: Optional[float] = None,
    llm_model: Optional[dict[str, Any]] = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Upsert one analysis row by ``(shipment_id, analysis_type)``. Returns ``{stored, id?, error?}``."""

    row_shipment_id = _uuid_or_none(shipments_row_id)
    if shipments_row_id and not row_shipment_id:
        return {"stored": False, "id": None, "error": "invalid_shipments_row_id"}
    if not row_shipment_id:
        return {"stored": False, "id": None, "error": "missing_shipments_row_id"}

    row_document_id = _uuid_or_none(document_id) if document_id else None
    if document_id and not row_document_id:
        return {"stored": False, "id": None, "error": "invalid_document_id"}

    row_id = str(uuid.uuid4())

    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                row = repos.document_analysis.upsert_by_shipment_and_type(
                    id=row_id,
                    shipment_id=row_shipment_id,
                    analysis_type=analysis_type.value,
                    results=results,
                    confidence_score=confidence_score,
                    llm_model=llm_model,
                    document_id=row_document_id,
                )
        if not row:
            return {"stored": False, "id": None, "error": "upsert_returned_no_row"}
        return {"stored": True, "id": row["id"], "updated_at": row["updated_at"]}
    except Exception as exc:
        logger.exception(
            "upsert_document_analysis failed shipment_id=%s analysis_type=%s",
            row_shipment_id,
            analysis_type.value,
        )
        return {"stored": False, "id": None, "error": str(exc)}


def read_ratecon_extraction(shipments_row_id: str | None) -> dict[str, Any]:
    """Load cached ``ratecon_extraction`` row for ``shipments_row_id``. Returns ``{found, row?, error?}``."""

    row_shipment_id = _uuid_or_none(shipments_row_id)
    if shipments_row_id and not row_shipment_id:
        return {"found": False, "error": "invalid_shipments_row_id"}
    if not row_shipment_id:
        return {"found": False, "error": "missing_shipments_row_id"}

    try:
        with db_scope() as repos:
            row = repos.document_analysis.get_by_shipment_and_type(
                shipment_id=row_shipment_id,
                analysis_type=DocumentAnalysisType.RATECON_EXTRACTION.value,
            )
        if not row:
            return {"found": False}
        if row.get("document_id") is not None:
            row["document_id"] = str(row["document_id"])
        return {"found": True, "row": row}
    except Exception as exc:
        logger.exception(
            "read_ratecon_extraction failed shipment_id=%s",
            row_shipment_id,
        )
        return {"found": False, "error": str(exc)}


def upsert_ratecon_extraction(
    shipments_row_id: str | None,
    *,
    results: dict[str, Any],
    confidence_score: Optional[float] = None,
    llm_model: Optional[dict[str, Any]] = None,
    document_id: str | None = None,
) -> dict[str, Any]:
    """Upsert ``ratecon_extraction`` for ``shipments_row_id``. Returns ``{stored, id?, error?}``."""

    return upsert_document_analysis(
        shipments_row_id,
        DocumentAnalysisType.RATECON_EXTRACTION,
        results=results,
        confidence_score=confidence_score,
        llm_model=llm_model,
        document_id=document_id,
    )
