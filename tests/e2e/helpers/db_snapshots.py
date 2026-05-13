"""Read-only Postgres snapshots for E2E (same ``DATABASE_URL`` as the app)."""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


def fetch_documents_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, type::text AS type, shipment_id, object_key, created_at
                FROM documents
                WHERE shipment_id = %s
                ORDER BY created_at ASC
                """,
                (shipment_id,),
            )
            rows = cur.fetchall()
            cols = ["id", "type", "shipment_id", "object_key", "created_at"]
            return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        conn.close()


def fetch_document_analysis_for_shipment(*, shipment_id: str) -> list[dict[str, Any]]:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, shipment_id, analysis_type::text AS analysis_type,
                       status, findings, attachments_used, created_at
                FROM document_analysis
                WHERE shipment_id = %s
                ORDER BY created_at ASC
                """,
                (shipment_id,),
            )
            rows = cur.fetchall()
            cols = [
                "id",
                "shipment_id",
                "analysis_type",
                "status",
                "findings",
                "attachments_used",
                "created_at",
            ]
            return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        conn.close()


def fetch_lifecycle_by_id(*, lifecycle_id: str) -> dict[str, Any] | None:
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
                FROM workflow_lifecycles
                WHERE id = %s
                """,
                (lifecycle_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [
                "id",
                "tenant_id",
                "workflow_name",
                "shipment_id",
                "email_thread_id",
                "updated_at",
            ]
            return dict(zip(cols, row, strict=True))
    finally:
        conn.close()


def fetch_ratecon_lifecycle_for_thread(*, tenant_id: str, thread_id: str) -> dict[str, Any] | None:
    """Latest ``ratecon`` lifecycle row for this Unipile ``thread_id`` (``email_thread_id``)."""
    tid = (tenant_id or "").strip()
    th = (thread_id or "").strip()
    if not tid or not th:
        return None
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
                FROM workflow_lifecycles
                WHERE tenant_id = %s
                  AND workflow_name = 'ratecon'
                  AND email_thread_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tid, th),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [
                "id",
                "tenant_id",
                "workflow_name",
                "shipment_id",
                "email_thread_id",
                "updated_at",
            ]
            return dict(zip(cols, row, strict=True))
    finally:
        conn.close()


def fetch_lifecycles_for_email_thread(*, tenant_id: str, thread_id: str) -> list[dict[str, Any]]:
    """All ``workflow_lifecycles`` rows for this Unipile ``thread_id`` (``email_thread_id``), any workflow."""
    tid = (tenant_id or "").strip()
    th = (thread_id or "").strip()
    if not tid or not th:
        return []
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
                FROM workflow_lifecycles
                WHERE tenant_id = %s AND email_thread_id = %s
                ORDER BY updated_at DESC
                """,
                (tid, th),
            )
            rows = cur.fetchall()
            cols = [
                "id",
                "tenant_id",
                "workflow_name",
                "shipment_id",
                "email_thread_id",
                "updated_at",
            ]
            return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        conn.close()


def fetch_lifecycles_for_tenant_shipment(*, tenant_id: str, shipment_id: str) -> list[dict[str, Any]]:
    """All ``workflow_lifecycles`` rows for this tenant and Turvo ``shipment_id`` (text match)."""
    tid = (tenant_id or "").strip()
    sid = str(shipment_id or "").strip()
    if not tid or not sid:
        return []
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, tenant_id, workflow_name, shipment_id, email_thread_id, updated_at
                FROM workflow_lifecycles
                WHERE tenant_id = %s AND shipment_id = %s
                ORDER BY updated_at DESC
                """,
                (tid, sid),
            )
            rows = cur.fetchall()
            cols = [
                "id",
                "tenant_id",
                "workflow_name",
                "shipment_id",
                "email_thread_id",
                "updated_at",
            ]
            return [dict(zip(cols, r, strict=True)) for r in rows]
    finally:
        conn.close()


def count_workflow_runs_for_shipment(*, tenant_id: str, shipment_id: str) -> int:
    """Count execution rows with this ``shipment_id`` (must match ``workflow_runs.shipment_id``)."""
    tid = (tenant_id or "").strip()
    sid = (shipment_id or "").strip()
    if not tid or not sid:
        return 0
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)::bigint
                FROM workflow_runs
                WHERE tenant_id = %s AND shipment_id = %s
                """,
                (tid, sid),
            )
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0
    finally:
        conn.close()
