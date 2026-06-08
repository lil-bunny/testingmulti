"""E2E read queries: load_tendering thread ↔ lifecycle via comms + runs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import fetchone_dict

from tests.db.e2e._tenant import resolve_tenant_uuid


def find_load_tendering_lifecycle_by_thread(
    session: Session,
    *,
    tenant_id: str,
    thread_id: str,
) -> dict[str, Any] | None:
    """Resolve ``load_tendering`` lifecycle id from earliest patched comm on thread."""
    tid = resolve_tenant_uuid(session, tenant_id)
    th = (thread_id or "").strip()
    if not tid or not th:
        return None
    return fetchone_dict(
        session,
        """
        SELECT wr.workflow_lifecycle_id::text AS lifecycle_id,
               wl.tender_id::text AS tender_id,
               wl.status::text AS status,
               wl.sub_status::text AS sub_status
        FROM communications c
        JOIN workflow_runs wr ON wr.id = c.workflow_run_id
        JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
        WHERE c.tenant_id = CAST(:tenant_id AS uuid)
          AND c.thread_id = :thread_id
          AND c.workflow_run_id IS NOT NULL
          AND wl.workflow_name = 'load_tendering'
        ORDER BY c.created_at ASC
        LIMIT 1
        """,
        {"tenant_id": tid, "thread_id": th},
    )
