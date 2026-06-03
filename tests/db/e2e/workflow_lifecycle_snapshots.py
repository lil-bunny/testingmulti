"""E2E read queries for ``workflow_lifecycles`` assertion snapshots."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchall_dicts, fetchone_dict

from tests.db.e2e._tenant import resolve_tenant_uuid

_TABLE = "workflow_lifecycles"

_WHERE_LIFECYCLE_ID = """
    WHERE id = CAST(:lifecycle_id AS uuid)
"""

_LOOKUP_ORDER_LIMIT = """
    ORDER BY updated_at DESC
    LIMIT 1
"""

_SNAPSHOT_SELECT = """
    SELECT id::text AS id,
           tenant_id::text AS tenant_id,
           workflow_name,
           shipment_id::text AS shipment_id,
           email_thread_id,
           updated_at
"""

_WHERE_TENANT_THREAD = """
    WHERE tenant_id = CAST(:tenant_id AS uuid)
      AND email_thread_id = :thread_id
"""


def read_by_id(session: Session, *, lifecycle_id: str) -> dict[str, Any] | None:
    lid = (lifecycle_id or "").strip()
    if not lid:
        return None
    return fetchone_dict(
        session,
        f"""
        {_SNAPSHOT_SELECT}
        FROM {_TABLE}
        {_WHERE_LIFECYCLE_ID}
        """,
        {"lifecycle_id": lid},
    )


def find_latest_ratecon_by_thread(
    session: Session,
    *,
    tenant_id: str,
    thread_id: str,
) -> dict[str, Any] | None:
    tid = resolve_tenant_uuid(session, tenant_id)
    th = (thread_id or "").strip()
    if not tid or not th:
        return None
    return fetchone_dict(
        session,
        f"""
        {_SNAPSHOT_SELECT}
        FROM {_TABLE}
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND workflow_name = 'ratecon'
          AND email_thread_id = :thread_id
        {_LOOKUP_ORDER_LIMIT}
        """,
        {"tenant_id": tid, "thread_id": th},
    )


def list_by_email_thread(
    session: Session,
    *,
    tenant_id: str,
    thread_id: str,
) -> list[dict[str, Any]]:
    tid = resolve_tenant_uuid(session, tenant_id)
    th = (thread_id or "").strip()
    if not tid or not th:
        return []
    return fetchall_dicts(
        session,
        f"""
        {_SNAPSHOT_SELECT}
        FROM {_TABLE}
        {_WHERE_TENANT_THREAD}
        ORDER BY updated_at DESC
        """,
        {"tenant_id": tid, "thread_id": th},
    )


def list_by_tenant_shipment(
    session: Session,
    *,
    tenant_id: str,
    shipment_id: str,
) -> list[dict[str, Any]]:
    tid = resolve_tenant_uuid(session, tenant_id)
    sid = str(shipment_id or "").strip()
    if not tid or not sid:
        return []
    return fetchall_dicts(
        session,
        f"""
        {_SNAPSHOT_SELECT}
        FROM {_TABLE}
        WHERE tenant_id = CAST(:tenant_id AS uuid)
          AND shipment_id::text = :shipment_id
        ORDER BY updated_at DESC
        """,
        {"tenant_id": tid, "shipment_id": sid},
    )
