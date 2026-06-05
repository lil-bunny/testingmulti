"""Postgres persistence for ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction
from app.models.document_analysis import DocumentAnalysisType

logger = logging.getLogger(__name__)


def upsert_document_analysis(
    shipment_id: str,
    analysis_type: DocumentAnalysisType,
    *,
    status: str,
    findings: dict[str, Any],
    confidence_score: Optional[float] = None,
    llm_model: Optional[dict[str, Any]] = None,
    attachments_used: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Upsert one analysis row by ``(shipment_id, analysis_type)``. Returns ``{stored, id?, error?}``."""

    if not shipment_id:
        return {"stored": False, "id": None, "error": "missing_shipment_id"}

    row_id = str(uuid.uuid4())

    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                row = repos.document_analysis.upsert_by_shipment_and_type(
                    id=row_id,
                    shipment_id=shipment_id,
                    analysis_type=analysis_type.value,
                    status=status,
                    findings=findings,
                    confidence_score=confidence_score,
                    llm_model=llm_model,
                    attachments_used=attachments_used,
                )
        if not row:
            return {"stored": False, "id": None, "error": "upsert_returned_no_row"}
        logger.info(
            "upsert_document_analysis: shipment_id=%s analysis_type=%s id=%s",
            shipment_id,
            analysis_type.value,
            row["id"],
        )
        return {"stored": True, "id": row["id"], "updated_at": row["updated_at"]}
    except Exception as exc:
        logger.exception(
            "upsert_document_analysis failed shipment_id=%s analysis_type=%s",
            shipment_id,
            analysis_type.value,
        )
        return {"stored": False, "id": None, "error": str(exc)}


def upsert_ratecon_extraction(
    shipment_id: str,
    *,
    status: str,
    findings: dict[str, Any],
    confidence_score: Optional[float] = None,
    llm_model: Optional[dict[str, Any]] = None,
    attachments_used: Optional[list[Any]] = None,
) -> dict[str, Any]:
    """Upsert ``ratecon_extraction`` for ``shipment_id``. Returns ``{stored, id?, error?}``."""

    return upsert_document_analysis(
        shipment_id,
        DocumentAnalysisType.RATECON_EXTRACTION,
        status=status,
        findings=findings,
        confidence_score=confidence_score,
        llm_model=llm_model,
        attachments_used=attachments_used,
    )
