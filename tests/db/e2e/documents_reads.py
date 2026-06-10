"""E2E read queries for ``documents``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts

_TABLE = "documents"


def list_by_shipment(session: Session, *, shipments_row_id: str) -> list[dict[str, Any]]:
    """All rows for a shipment (``shipments.id`` UUID), oldest ``created_at`` first."""
    return fetchall_dicts(
        session,
        f"""
        SELECT id, type::text AS type, shipment_id, storage_key, created_at
        FROM {_TABLE}
        WHERE shipment_id = :shipments_row_id
        ORDER BY created_at ASC
        """,
        {"shipments_row_id": shipments_row_id},
    )
