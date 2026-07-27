"""
Postgres write helpers for ``document_analysis`` rows (upsert-by-type).

Ratecon page-count *reads* for the POD strip pipeline live in
``app.services.pod_lifecycle.strip_ratecon_pages``.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.db import db_scope, db_transaction
from app.models.document_analysis import (
    DOCUMENT_ANALYSIS_PAGE_COUNT_KEY,
    DocumentAnalysisType,
)
from app.tools.documents import _uuid_or_none

logger = logging.getLogger(__name__)


def normalize_page_count(value: Any) -> int | None:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n >= 1 else None


def metadata_with_page_count(page_count: Any = None) -> dict[str, Any] | None:
    """Build a ``document_analysis.metadata`` patch with ``page_count`` when valid."""
    n = normalize_page_count(page_count)
    if n is None:
        return None
    return {DOCUMENT_ANALYSIS_PAGE_COUNT_KEY: n}


def upsert_document_analysis(
    shipments_row_id: str | None,
    analysis_type: DocumentAnalysisType,
    *,
    results: dict[str, Any],
    confidence_score: Optional[float] = None,
    llm_model: Optional[dict[str, Any]] = None,
    document_id: str | None = None,
    page_count: Any = None,
    metadata: dict[str, Any] | None = None,
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

    meta_patch: dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    page_patch = metadata_with_page_count(page_count)
    if page_patch:
        meta_patch.update(page_patch)

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
                    metadata=meta_patch or None,
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
