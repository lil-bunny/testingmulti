"""Read-only ``workflow_runs`` queries and execution-id parsing for E2E."""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings

_WORKFLOW_RUNS_TABLE = "workflow_runs"


def _conn() -> psycopg.Connection:
    return psycopg.connect(settings.DATABASE_URL)

def fetch_latest_workflow_run_for_tenant_shipment(
    tenant_id: str,
    shipment_id: str,
) -> dict[str, Any] | None:
    """Latest ``workflow_runs`` row for tenant + shipment (newest ``created_at`` first)."""
    tid = str(tenant_id).strip()
    sid = str(shipment_id).strip()
    if not tid or not sid:
        return None
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, tenant_id, event_type, workflow_lifecycle_id, shipment_id
                FROM {_WORKFLOW_RUNS_TABLE}
                WHERE tenant_id = %s AND shipment_id IS NOT DISTINCT FROM %s
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (tid, sid),
            )
            row = cur.fetchone()
            if row is None:
                return None
            return {
                "id": row[0],
                "tenant_id": row[1],
                "event_type": row[2],
                "workflow_lifecycle_id": row[3],
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
                SELECT id, tenant_id, event_type, workflow_lifecycle_id, shipment_id, created_at
                FROM {_WORKFLOW_RUNS_TABLE}
                WHERE workflow_lifecycle_id = %s AND event_type = %s
                ORDER BY created_at ASC
                """,
                (wl, et),
            )
            rows = cur.fetchall()
            out: list[dict[str, Any]] = []
            for row in rows:
                out.append(
                    {
                        "id": row[0],
                        "tenant_id": row[1],
                        "event_type": row[2],
                        "workflow_lifecycle_id": row[3],
                        "shipment_id": row[4],
                        "created_at": row[5],
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
