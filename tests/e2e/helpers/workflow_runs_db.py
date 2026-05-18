"""Read-only ``workflow_runs`` queries and execution-id parsing for E2E."""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid

_WORKFLOW_RUNS_TABLE = "workflow_runs"


def _conn() -> psycopg.Connection:
    return psycopg.connect(settings.DATABASE_URL)


def _tenant_uuid_for_queries(tenant_id: str) -> str:
    tid = tenant_id.strip()
    if not tid:
        raise ValueError("tenant_id required")
    u = resolve_graph_tenant_to_uuid(tid)
    if not u:
        raise ValueError(
            f"No tenants.slug match for graph tenant_id={tenant_id!r} (workflow_runs uses UUID)."
        )
    return u


def fetch_latest_workflow_run_for_tenant_shipment(
    tenant_id: str,
    shipment_id: str,
) -> dict[str, Any] | None:
    """Latest ``workflow_runs`` row tied to lifecycle rows with this shipment (newest ``created_at``)."""
    tenant_uuid = _tenant_uuid_for_queries(tenant_id)
    sid = str(shipment_id).strip()
    if not sid:
        return None
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT wr.id, wr.tenant_id, wr.event_type, wr.workflow_lifecycle_id, wl.shipment_id
                FROM {_WORKFLOW_RUNS_TABLE} wr
                INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
                WHERE wr.tenant_id = %s::uuid AND wl.shipment_id IS NOT DISTINCT FROM %s
                ORDER BY wr.created_at DESC
                LIMIT 1
                """,
                (tenant_uuid, sid),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "id": str(row[0]),
                "tenant_id": str(row[1]),
                "event_type": row[2],
                "workflow_lifecycle_id": str(row[3]),
                "shipment_id": row[4],
            }
    finally:
        conn.close()


def list_workflow_runs_for_lifecycle_event_type(
    workflow_lifecycle_id: str,
    event_type: str,
) -> list[dict[str, Any]]:
    """All matching rows for one lifecycle and ``event_type``, ``created_at`` ascending."""
    wl = str(workflow_lifecycle_id).strip()
    et = str(event_type).strip()
    if not wl or not et:
        return []
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT wr.id, wr.tenant_id, wr.event_type, wr.workflow_lifecycle_id,
                       wr.created_at, wr.status
                FROM {_WORKFLOW_RUNS_TABLE} wr
                WHERE wr.workflow_lifecycle_id = %s::uuid AND wr.event_type = %s
                ORDER BY wr.created_at ASC
                """,
                (wl, et),
            )
            rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                out.append(
                    {
                        "id": str(row[0]),
                        "tenant_id": str(row[1]),
                        "event_type": row[2],
                        "workflow_lifecycle_id": str(row[3]),
                        "created_at": row[4],
                        "status": row[5],
                        "shipment_id": None,
                    }
                )
            return out
    finally:
        conn.close()


def execution_id_from_webhook_response(body: Any) -> str | None:
    """``execution_id`` from Unipile webhook JSON (top-level or under ``data``)."""
    if not isinstance(body, dict):
        return None
    top = body.get("execution_id")
    if top is not None and str(top).strip():
        return str(top).strip()
    data = body.get("data")
    if isinstance(data, dict):
        nested = data.get("execution_id")
        if nested is not None and str(nested).strip():
            return str(nested).strip()
    return None
