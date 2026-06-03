"""E2E read queries for ``document_analysis``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts

_TABLE = "document_analysis"
_JSONB_KEYS = frozenset({"findings", "llm_model", "attachments_used"})


def list_by_shipment(session: Session, *, shipment_id: str) -> list[dict[str, Any]]:
    """All rows for a shipment, oldest ``created_at`` first."""
    return fetchall_dicts(
        session,
        f"""
        SELECT id, shipment_id, analysis_type::text AS analysis_type,
               status, findings, attachments_used, created_at
        FROM {_TABLE}
        WHERE shipment_id = :shipment_id
        ORDER BY created_at ASC
        """,
        {"shipment_id": shipment_id},
        json_keys=_JSONB_KEYS,
    )
