"""E2E read queries for ``documents``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts

_TABLE = "documents"


def list_by_shipment(session: Session, *, shipment_id: str) -> list[dict[str, Any]]:
    """All rows for a shipment, oldest ``created_at`` first."""
    return fetchall_dicts(
        session,
        f"""
        SELECT id, type::text AS type, shipment_id, object_key, created_at
        FROM {_TABLE}
        WHERE shipment_id = :shipment_id
        ORDER BY created_at ASC
        """,
        {"shipment_id": shipment_id},
    )
