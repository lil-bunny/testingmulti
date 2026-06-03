"""Postgres persistence for ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction, fetchone_dict
from app.models.document_analysis import DocumentAnalysisType

logger = logging.getLogger(__name__)

TABLE_NAME = "document_analysis"


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
    sql = f"""
        INSERT INTO {TABLE_NAME} (
            id, shipment_id, analysis_type, status, confidence_score,
            llm_model, attachments_used, findings
        )
        VALUES (
            :id, :shipment_id, :analysis_type, :status, :confidence_score,
            :llm_model, :attachments_used, :findings
        )
        ON CONFLICT (shipment_id, analysis_type) DO UPDATE SET
            status = EXCLUDED.status,
            confidence_score = EXCLUDED.confidence_score,
            llm_model = EXCLUDED.llm_model,
            attachments_used = EXCLUDED.attachments_used,
            findings = EXCLUDED.findings,
            updated_at = NOW()
        RETURNING id, updated_at
    """
    params = {
        "id": row_id,
        "shipment_id": shipment_id,
        "analysis_type": analysis_type.value,
        "status": status,
        "confidence_score": confidence_score,
        "llm_model": llm_model,
        "attachments_used": attachments_used,
        "findings": findings,
    }

    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                row = fetchone_dict(repos.session, sql, params)
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
