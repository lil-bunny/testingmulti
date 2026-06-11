"""Read-only ``workflow_runs`` queries and execution-id parsing for E2E."""

from __future__ import annotations

from typing import Any

from app.core.db import db_scope

from tests.db.e2e import workflow_runs_reads


def fetch_latest_workflow_run_for_tenant_shipment(
    tenant_id: str,
    shipment_id: str,
) -> dict[str, Any] | None:
    """Latest ``workflow_runs`` row tied to lifecycle rows with this shipment (newest ``created_at``)."""
    with db_scope() as repos:
        return workflow_runs_reads.fetch_latest_by_tenant_shipment(
            repos.session,
            tenant_id=tenant_id,
            shipment_id=shipment_id,
        )


def list_workflow_runs_for_lifecycle_event_type(
    workflow_lifecycle_id: str,
    event_type: str,
) -> list[dict[str, Any]]:
    """All matching rows for one lifecycle and ``event_type``, ``created_at`` ascending."""
    with db_scope() as repos:
        rows = workflow_runs_reads.list_by_lifecycle_event_type(
            repos.session,
            workflow_lifecycle_id=workflow_lifecycle_id,
            event_type=event_type,
        )
    return [{**row, "shipment_id": None} for row in rows]


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
