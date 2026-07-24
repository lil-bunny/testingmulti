"""E2E read queries for ``document_analysis``."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING


from app.core.db import fetchall_dicts

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_TABLE = "document_analysis"
_JSONB_KEYS = frozenset({"results", "llm_model"})


def list_by_shipment(session: Session, *, shipments_row_id: str) -> list[dict[str, Any]]:
    """All rows for a shipment (``shipments.id`` UUID), oldest ``created_at`` first."""
    return fetchall_dicts(
        session,
        f"""
        SELECT id, shipment_id, analysis_type::text AS analysis_type,
               results, document_id, created_at
        FROM {_TABLE}
        WHERE shipment_id = :shipments_row_id
        ORDER BY created_at ASC
        """,
        {"shipments_row_id": shipments_row_id},
        json_keys=_JSONB_KEYS,
    )
