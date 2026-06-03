"""Read/write ``document_analysis`` (ratecon / POD extraction rows)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchone_dict, jsonb_param


class DocumentAnalysisRepository:
    TABLE_NAME = "document_analysis"

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_by_shipment_and_type(
        self,
        *,
        id: str,
        shipment_id: str,
        analysis_type: str,
        status: str,
        findings: dict[str, Any],
        confidence_score: float | None = None,
        llm_model: dict[str, Any] | None = None,
        attachments_used: list[Any] | None = None,
    ) -> dict[str, Any] | None:
        """Upsert by ``(shipment_id, analysis_type)``; return ``id`` and ``updated_at``."""
        return fetchone_dict(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (
                id, shipment_id, analysis_type, status, confidence_score,
                llm_model, attachments_used, findings
            )
            VALUES (
                :id, :shipment_id, :analysis_type, :status, :confidence_score,
                CAST(:llm_model AS jsonb),
                CAST(:attachments_used AS jsonb),
                CAST(:findings AS jsonb)
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
            {
                "id": id,
                "shipment_id": shipment_id,
                "analysis_type": analysis_type,
                "status": status,
                "confidence_score": confidence_score,
                "llm_model": jsonb_param(llm_model),
                "attachments_used": jsonb_param(attachments_used),
                "findings": jsonb_param(findings),
            },
        )
