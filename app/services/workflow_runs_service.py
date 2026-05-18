"""Service layer for workflow_runs table.

Pure execution log — one row per graph invocation, keyed by execution_id (PK).
``tenant_id`` is stored as ``tenants.id`` (UUID). Graph/config keys such as ``t3ra`` are
resolved via ``tenants.slug`` before insert/query.

Shipment correlation for dedupe lives on ``workflow_lifecycles``, not duplicated here.
"""

from __future__ import annotations

from typing import Any

import psycopg

from app.core.config import settings
from app.core.logger import get_logger
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid

logger = get_logger(__name__)


class WorkflowRunsService:

    TABLE_NAME = "workflow_runs"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

    @staticmethod
    def _clean(val: str | None) -> str | None:
        if val is None:
            return None
        s = str(val).strip()
        return s if s else None

    def _tenant_uuid_or_none(self, tenant_id: str | None) -> str | None:
        """Resolve graph/config tenant key or UUID string to canonical tenant UUID."""

        return resolve_graph_tenant_to_uuid(self._clean(tenant_id))

    @staticmethod
    def reminder_run_event_type(reminder_step: int | None) -> str | None:
        """DB ``event_type`` for a Celery POD reminder."""
        if reminder_step is None:
            return None
        return f"reminder_{int(reminder_step)}"

    def is_workflow_initial_path_blocked(
        self,
        *,
        tenant_id: str | None,
        event_type: str | None,
        workflow_lifecycle_id: str | None,
        shipment_id: str | None,
        exclude_run_id: str | None = None,
    ) -> bool:
        """
        Whether a prior recorded run already covers this ``route_completed`` trigger.

        Matches either same ``workflow_lifecycle_id`` + ``route_completed`` or any run for the same
        tenant shipment (via ``workflow_lifecycles.shipment_id``). Requires resolvable UUID ``tenant_id``.
        """
        tid = self._tenant_uuid_or_none(tenant_id)
        wl = self._clean(workflow_lifecycle_id)
        et = self._clean(event_type)
        sid = self._clean(shipment_id)
        exc = self._clean(exclude_run_id)

        if not tid or not wl or et != "route_completed" or not sid:
            return False

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT EXISTS (
                        SELECT 1 FROM {self.TABLE_NAME} wr
                        WHERE trim(both wr.workflow_lifecycle_id::text) = trim(both %s::text)
                          AND wr.event_type = %s
                          AND (%s::text IS NULL OR trim(both wr.id::text) != trim(both %s::text))
                        UNION ALL
                        SELECT 1 FROM {self.TABLE_NAME} wr
                        INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
                        WHERE trim(both wr.tenant_id::text) = trim(both %s::text)
                          AND wr.event_type = 'route_completed'
                          AND wl.shipment_id IS NOT DISTINCT FROM %s
                          AND (%s::text IS NULL OR trim(both wr.id::text) != trim(both %s::text))
                    )
                    """,
                    (wl, et, exc, exc, tid, sid, exc, exc),
                )
                row = cur.fetchone()
                return bool(row and row[0])
        finally:
            conn.close()

    def record_workflow_run(
        self,
        *,
        run_id: str,
        tenant_id: str | None,
        event_type: str,
        workflow_lifecycle_id: str | None,
    ) -> bool:
        """Insert one execution-log row. Returns True on success, False if required fields are missing."""
        tid_uuid = self._tenant_uuid_or_none(tenant_id)
        wl = self._clean(workflow_lifecycle_id)
        et = (event_type or "").strip()
        rid = self._clean(run_id)

        if not tid_uuid or not wl or not et or not rid:
            if not tid_uuid and self._clean(tenant_id):
                logger.warning(
                    "workflow_runs skipped: cannot resolve tenant_id=%r to tenants.id (UUID)",
                    tenant_id,
                )
            return False

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        id, tenant_id, event_type,
                        workflow_lifecycle_id
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (rid, tid_uuid, et, wl),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def fetch_workflow_run_by_id(self, *, run_id: str) -> dict[str, Any] | None:
        """Return one execution row by primary key."""

        rid = self._clean(run_id)
        if not rid:
            return None
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, tenant_id, event_type, workflow_lifecycle_id,
                           created_at, status, updated_at
                    FROM {self.TABLE_NAME}
                    WHERE trim(both id::text) = trim(both %s::text)
                    """,
                    (rid,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": str(row[0]),
                    "tenant_id": str(row[1]),
                    "event_type": row[2],
                    "workflow_lifecycle_id": str(row[3]),
                    "created_at": row[4],
                    "status": row[5],
                    "updated_at": row[6],
                }
        finally:
            conn.close()
