"""Postgres persistence for ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

import psycopg
from psycopg.types.json import Json

from app.core.config import settings
from app.models.document_analysis import DocumentAnalysisType

logger = logging.getLogger(__name__)

_PG_READY = False


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


def _table() -> str:
    return settings.DOCUMENT_ANALYSIS_TABLE


def _analysis_type_sql_in() -> str:
    return ", ".join(f"'{m.value}'" for m in DocumentAnalysisType)


def _ensure_table() -> None:
    global _PG_READY
    if _PG_READY:
        return
    t = _table()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {t} (
                    id TEXT PRIMARY KEY,
                    shipment_id TEXT NOT NULL,
                    analysis_type TEXT NOT NULL
                        CHECK (
                            analysis_type IN ({_analysis_type_sql_in()})
                        ),
                    status TEXT,
                    confidence_score DOUBLE PRECISION,
                    llm_model JSONB,
                    attachments_used JSONB,
                    findings JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (shipment_id, analysis_type)
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{t}_shipment_id ON {t}(shipment_id)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{t}_analysis_type ON {t}(analysis_type)"
            )
        conn.commit()
        _PG_READY = True
        logger.info("document_analysis: ensured table %s exists", t)
    finally:
        conn.close()


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

    _ensure_table()
    row_id = str(uuid.uuid4())
    t = _table()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {t} (
                    id, shipment_id, analysis_type, status, confidence_score,
                    llm_model, attachments_used, findings
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s
                )
                ON CONFLICT (shipment_id, analysis_type) DO UPDATE SET
                    status = EXCLUDED.status,
                    confidence_score = EXCLUDED.confidence_score,
                    llm_model = EXCLUDED.llm_model,
                    attachments_used = EXCLUDED.attachments_used,
                    findings = EXCLUDED.findings,
                    updated_at = NOW()
                RETURNING id, updated_at
                """,
                (
                    row_id,
                    shipment_id,
                    analysis_type.value,
                    status,
                    confidence_score,
                    Json(llm_model) if llm_model is not None else None,
                    Json(attachments_used) if attachments_used is not None else None,
                    Json(findings),
                ),
            )
            row = cur.fetchone()
        conn.commit()
        if not row:
            return {"stored": False, "id": None, "error": "upsert_returned_no_row"}
        logger.info(
            "upsert_document_analysis: shipment_id=%s analysis_type=%s id=%s",
            shipment_id,
            analysis_type.value,
            row[0],
        )
        return {"stored": True, "id": row[0], "updated_at": row[1]}
    except Exception as exc:
        logger.exception(
            "upsert_document_analysis failed shipment_id=%s analysis_type=%s",
            shipment_id,
            analysis_type.value,
        )
        return {"stored": False, "id": None, "error": str(exc)}
    finally:
        conn.close()


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
