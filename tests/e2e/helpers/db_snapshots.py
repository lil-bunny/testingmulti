"""Read-only Postgres snapshots for E2E (same ``DATABASE_URL`` as the app)."""

from __future__ import annotations

from typing import Any

from app.core.db import db_scope, fetchall_dicts, fetchone_dict
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid


def fetch_documents_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT id, type::text AS type, shipment_id, object_key, created_at
        FROM documents
        WHERE shipment_id = :shipment_id
        ORDER BY created_at ASC
    """
    with db_scope() as repos:
        return fetchall_dicts(repos.session, sql, {"shipment_id": shipment_id})


def fetch_document_analysis_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    sql = """
        SELECT id, shipment_id, analysis_type::text AS analysis_type,
               status, findings, attachments_used, created_at
        FROM document_analysis
        WHERE shipment_id = :shipment_id
        ORDER BY created_at ASC
    """
    with db_scope() as repos:
        return fetchall_dicts(repos.session, sql, {"shipment_id": shipment_id})


def fetch_lifecycle_by_id(*, lifecycle_id: str) -> dict[str, Any] | None:
    sql = """
        SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
        FROM workflow_lifecycles
        WHERE id = :lifecycle_id
    """
    with db_scope() as repos:
        return fetchone_dict(repos.session, sql, {"lifecycle_id": lifecycle_id})


def fetch_ratecon_lifecycle_for_thread(*, tenant_id: str, thread_id: str) -> dict[str, Any] | None:
    """Latest ``ratecon`` lifecycle row for this Unipile ``thread_id`` (``email_thread_id``)."""
    tid = (tenant_id or "").strip()
    th = (thread_id or "").strip()
    if not tid or not th:
        return None
    sql = """
        SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
        FROM workflow_lifecycles
        WHERE tenant_id = :tenant_id
          AND workflow_name = 'ratecon'
          AND email_thread_id = :thread_id
        ORDER BY updated_at DESC
        LIMIT 1
    """
    with db_scope() as repos:
        return fetchone_dict(
            repos.session, sql, {"tenant_id": tid, "thread_id": th}
        )


def fetch_lifecycles_for_email_thread(*, tenant_id: str, thread_id: str) -> list[dict[str, Any]]:
    """All ``workflow_lifecycles`` rows for this Unipile ``thread_id`` (``email_thread_id``), any workflow."""
    tid = (tenant_id or "").strip()
    th = (thread_id or "").strip()
    if not tid or not th:
        return []
    sql = """
        SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
        FROM workflow_lifecycles
        WHERE tenant_id = :tenant_id AND email_thread_id = :thread_id
        ORDER BY updated_at DESC
    """
    with db_scope() as repos:
        return fetchall_dicts(
            repos.session, sql, {"tenant_id": tid, "thread_id": th}
        )


def fetch_lifecycles_for_tenant_shipment(*, tenant_id: str, shipment_id: str) -> list[dict[str, Any]]:
    """All ``workflow_lifecycles`` rows for this tenant and Turvo ``shipment_id`` (text match)."""
    tid = (tenant_id or "").strip()
    sid = str(shipment_id or "").strip()
    if not tid or not sid:
        return []
    sql = """
        SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
        FROM workflow_lifecycles
        WHERE tenant_id = :tenant_id AND shipment_id = :shipment_id
        ORDER BY updated_at DESC
    """
    with db_scope() as repos:
        return fetchall_dicts(
            repos.session, sql, {"tenant_id": tid, "shipment_id": sid}
        )


def count_workflow_runs_for_shipment(*, tenant_id: str, shipment_id: str) -> int:
    """Count workflow_runs executions whose lifecycle ties this tenant UUID and shipment_id."""

    tid_raw = (tenant_id or "").strip()
    sid = (shipment_id or "").strip()
    if not tid_raw or not sid:
        return 0
    tid = resolve_graph_tenant_to_uuid(tid_raw)
    if not tid:
        return 0

    sql = """
        SELECT COUNT(*)::bigint AS count
        FROM workflow_runs wr
        INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
        WHERE wr.tenant_id = CAST(:tenant_id AS uuid) AND wl.shipment_id = :shipment_id
    """
    with db_scope() as repos:
        row = fetchone_dict(
            repos.session,
            sql,
            {"tenant_id": tid, "shipment_id": sid},
        )
        if not row:
            return 0
        return int(row["count"] or 0)
