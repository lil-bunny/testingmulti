"""E2E read queries for ``workflow_runs``."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts, fetchone_dict

from tests.db.e2e._tenant import resolve_tenant_uuid

_TABLE = "workflow_runs"


def _clean(val: str | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def count_by_tenant_shipment(
    session: Session,
    *,
    tenant_id: str,
    shipment_id: str,
) -> int:
    tid = resolve_tenant_uuid(session, tenant_id)
    sid = _clean(shipment_id)
    if not tid or not sid:
        return 0
    row = fetchone_dict(
        session,
        f"""
        SELECT COUNT(*)::bigint AS count
        FROM {_TABLE} wr
        INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
        WHERE wr.tenant_id = CAST(:tenant_id AS uuid)
          AND wl.shipment_id::text = :shipment_id
        """,
        {"tenant_id": tid, "shipment_id": sid},
    )
    if not row:
        return 0
    return int(row["count"] or 0)


def fetch_latest_by_tenant_shipment(
    session: Session,
    *,
    tenant_id: str,
    shipment_id: str,
) -> dict[str, Any] | None:
    tid = resolve_tenant_uuid(session, tenant_id)
    sid = _clean(shipment_id)
    if not tid or not sid:
        return None
    row = fetchone_dict(
        session,
        f"""
        SELECT wr.id::text AS id,
               wr.tenant_id::text AS tenant_id,
               wr.event_type,
               wr.workflow_lifecycle_id::text AS workflow_lifecycle_id,
               wl.shipment_id::text AS shipment_id
        FROM {_TABLE} wr
        INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
        WHERE wr.tenant_id = CAST(:tenant_id AS uuid)
          AND wl.shipment_id::text IS NOT DISTINCT FROM :shipment_id
        ORDER BY wr.created_at DESC
        LIMIT 1
        """,
        {"tenant_id": tid, "shipment_id": sid},
    )
    if row is None:
        return None
    return {
        "id": str(row["id"]),
        "tenant_id": str(row["tenant_id"]),
        "event_type": row["event_type"],
        "workflow_lifecycle_id": str(row["workflow_lifecycle_id"]),
        "shipment_id": row["shipment_id"],
    }


def list_by_lifecycle_event_type(
    session: Session,
    *,
    workflow_lifecycle_id: str,
    event_type: str,
) -> list[dict[str, Any]]:
    wl = _clean(workflow_lifecycle_id)
    et = _clean(event_type)
    if not wl or not et:
        return []
    rows = fetchall_dicts(
        session,
        f"""
        SELECT wr.id::text AS id,
               wr.tenant_id::text AS tenant_id,
               wr.event_type,
               wr.workflow_lifecycle_id::text AS workflow_lifecycle_id,
               wr.created_at
        FROM {_TABLE} wr
        WHERE wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
          AND wr.event_type = :event_type
        ORDER BY wr.created_at ASC
        """,
        {"workflow_lifecycle_id": wl, "event_type": et},
    )
    return [
        {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "event_type": row["event_type"],
            "workflow_lifecycle_id": str(row["workflow_lifecycle_id"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]
