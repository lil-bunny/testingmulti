"""Read-only ``workflow_runs`` queries and execution-id parsing for E2E."""

from __future__ import annotations

from typing import Any

from app.core.db import db_scope, fetchall_dicts, fetchone_dict
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid

_WORKFLOW_RUNS_TABLE = "workflow_runs"


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
    sql = f"""
        SELECT wr.id, wr.tenant_id, wr.event_type, wr.workflow_lifecycle_id, wl.shipment_id
        FROM {_WORKFLOW_RUNS_TABLE} wr
        INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
        WHERE wr.tenant_id = CAST(:tenant_id AS uuid) AND wl.shipment_id IS NOT DISTINCT FROM :shipment_id
        ORDER BY wr.created_at DESC
        LIMIT 1
    """
    with db_scope() as repos:
        row = fetchone_dict(
            repos.session, sql, {"tenant_id": tenant_uuid, "shipment_id": sid}
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


def list_workflow_runs_for_lifecycle_event_type(
    workflow_lifecycle_id: str,
    event_type: str,
) -> list[dict[str, Any]]:
    """All matching rows for one lifecycle and ``event_type``, ``created_at`` ascending."""
    wl = str(workflow_lifecycle_id).strip()
    et = str(event_type).strip()
    if not wl or not et:
        return []
    sql = f"""
        SELECT wr.id, wr.tenant_id, wr.event_type, wr.workflow_lifecycle_id,
               wr.created_at
        FROM {_WORKFLOW_RUNS_TABLE} wr
        WHERE wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
          AND wr.event_type = :event_type
        ORDER BY wr.created_at ASC
    """
    with db_scope() as repos:
        rows = fetchall_dicts(
            repos.session,
            sql,
            {"workflow_lifecycle_id": wl, "event_type": et},
        )
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "id": str(row["id"]),
                "tenant_id": str(row["tenant_id"]),
                "event_type": row["event_type"],
                "workflow_lifecycle_id": str(row["workflow_lifecycle_id"]),
                "created_at": row["created_at"],
                "shipment_id": None,
            }
        )
    return out


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
