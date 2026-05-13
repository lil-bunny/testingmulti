"""Service layer for workflow_runs table.

Pure execution log — one row per graph invocation, keyed by execution_id (PK).
Dedup for route_completed is handled via read-based checks, not insert constraints.
"""

from __future__ import annotations

import uuid

import psycopg

from app.core.config import settings


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
        Whether a prior recorded run already covers this ``route_completed`` trigger
        (replay or duplicate Turvo webhook).

        Excludes the current run (``exclude_run_id``) so a run doesn't block itself.
        Requires ``shipment_id``; load-only route signals are not deduped via this table.
        """
        tid = self._clean(tenant_id)
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
                        WHERE wr.workflow_lifecycle_id = %s
                          AND wr.event_type = %s
                          AND (%s::text IS NULL OR wr.id != %s::text)
                        UNION ALL
                        SELECT 1 FROM {self.TABLE_NAME} wr
                        WHERE wr.tenant_id = %s
                          AND wr.event_type = 'route_completed'
                          AND wr.shipment_id IS NOT DISTINCT FROM %s
                          AND (%s::text IS NULL OR wr.id != %s::text)
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
        shipment_id: str | None = None,
    ) -> bool:
        """Insert one execution-log row. Returns True on success, False if required fields are missing."""
        tid = self._clean(tenant_id)
        wl = self._clean(workflow_lifecycle_id)
        et = (event_type or "").strip()

        if not tid or not wl or not et:
            return False

        sid = self._clean(shipment_id)

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        id, tenant_id, event_type,
                        workflow_lifecycle_id, shipment_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (run_id, tid, et, wl, sid),
                )
            conn.commit()
            return True
        finally:
            conn.close()

    def update_run_shipment_id(self, *, run_id: str, shipment_id: str) -> None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.TABLE_NAME} SET shipment_id = %s WHERE id = %s AND shipment_id IS NULL",
                    (self._clean(shipment_id), run_id),
                )
            conn.commit()
        finally:
            conn.close()