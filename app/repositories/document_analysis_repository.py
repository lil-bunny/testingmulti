"""Read/write ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchone_dict, jsonb_param


_JSONB_KEYS = frozenset({"results", "llm_model"})


class DocumentAnalysisRepository:
    TABLE_NAME = "document_analysis"

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_shipment_and_type(
        self,
        *,
        shipment_id: str,
        analysis_type: str,
    ) -> dict[str, Any] | None:
        """Return the row for ``(shipment_id, analysis_type)``, or ``None``."""
        return fetchone_dict(
            self._session,
            f"""
            SELECT id, shipment_id, analysis_type, confidence_score,
                   llm_model, document_id, results, updated_at
            FROM {self.TABLE_NAME}
            WHERE shipment_id = :shipment_id AND analysis_type = :analysis_type
            LIMIT 1
            """,
            {"shipment_id": shipment_id, "analysis_type": analysis_type},
            json_keys=_JSONB_KEYS,
        )

    def upsert_by_shipment_and_type(
        self,
        *,
        id: str,
        shipment_id: str,
        analysis_type: str,
        results: dict[str, Any],
        confidence_score: float | None = None,
        llm_model: dict[str, Any] | None = None,
        document_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Upsert by ``(shipment_id, analysis_type)``; return ``id`` and ``updated_at``."""
        return fetchone_dict(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (
                id, shipment_id, analysis_type, confidence_score,
                llm_model, document_id, results
            )
            VALUES (
                :id, :shipment_id, :analysis_type, :confidence_score,
                CAST(:llm_model AS jsonb),
                CAST(:document_id AS uuid),
                CAST(:results AS jsonb)
            )
            ON CONFLICT (shipment_id, analysis_type) DO UPDATE SET
                confidence_score = EXCLUDED.confidence_score,
                llm_model = EXCLUDED.llm_model,
                document_id = EXCLUDED.document_id,
                results = EXCLUDED.results,
                updated_at = NOW()
            RETURNING id, updated_at
            """,
            {
                "id": id,
                "shipment_id": shipment_id,
                "analysis_type": analysis_type,
                "confidence_score": confidence_score,
                "llm_model": jsonb_param(llm_model),
                "document_id": document_id,
                "results": jsonb_param(results),
            },
        )
