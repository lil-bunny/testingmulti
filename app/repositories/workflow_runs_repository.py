"""Reads/writes for ``workflow_runs`` (graph execution log)."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import execute_scalar, fetchone_dict
from app.core.logger import get_logger
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid

logger = get_logger(__name__)


class WorkflowRunsRepository:
    TABLE_NAME = "workflow_runs"

    def __init__(self, session: Session) -> None:
        self._session = session

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
    def _uuid_or_none(val: str | None) -> str | None:
        raw = WorkflowRunsRepository._clean(val)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError, TypeError):
            return None

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
        sid_uuid = self._uuid_or_none(sid)
        exc = self._clean(exclude_run_id)

        if not tid or not wl or et != "route_completed" or not sid:
            return False

        shipment_match_sql = ""
        params: dict[str, Any] = {"wl": wl, "et": et, "exc": exc, "tid": tid}
        if sid_uuid:
            shipment_match_sql = """
                UNION ALL
                SELECT 1 FROM {table} wr
                INNER JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
                WHERE trim(both wr.tenant_id::text) = trim(both CAST(:tid AS text))
                  AND wr.event_type = 'route_completed'
                  AND wl.shipment_id IS NOT DISTINCT FROM CAST(:sid_uuid AS uuid)
                  AND (CAST(:exc AS text) IS NULL OR trim(both wr.id::text) != trim(both CAST(:exc AS text)))
            """.format(table=self.TABLE_NAME)
            params["sid_uuid"] = sid_uuid

        exists = execute_scalar(
            self._session,
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {self.TABLE_NAME} wr
                WHERE trim(both wr.workflow_lifecycle_id::text) = trim(both CAST(:wl AS text))
                  AND wr.event_type = :et
                  AND (CAST(:exc AS text) IS NULL OR trim(both wr.id::text) != trim(both CAST(:exc AS text)))
                {shipment_match_sql}
            )
            """,
            params,
        )
        return bool(exists)

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

        self._session.execute(
            text(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    id, tenant_id, event_type,
                    workflow_lifecycle_id
                )
                VALUES (
                    :run_id,
                    CAST(:tenant_id AS uuid),
                    :event_type,
                    :workflow_lifecycle_id
                )
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "run_id": rid,
                "tenant_id": tid_uuid,
                "event_type": et,
                "workflow_lifecycle_id": wl,
            },
        )
        return True

    def fetch_workflow_run_by_id(self, *, run_id: str) -> dict[str, Any] | None:
        """Return one execution row by primary key."""
        rid = self._clean(run_id)
        if not rid:
            return None

        row = fetchone_dict(
            self._session,
            f"""
            SELECT id::text AS id,
                   tenant_id::text AS tenant_id,
                   event_type,
                   workflow_lifecycle_id::text AS workflow_lifecycle_id,
                   created_at,
                   updated_at
            FROM {self.TABLE_NAME}
            WHERE trim(both id::text) = trim(both CAST(:run_id AS text))
            """,
            {"run_id": rid},
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "event_type": row["event_type"],
            "workflow_lifecycle_id": str(row["workflow_lifecycle_id"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def find_latest_by_lifecycle_id(self, *, lifecycle_id: str) -> dict[str, Any] | None:
        """Most recent ``workflow_runs`` row for a lifecycle (for API activity logging)."""
        wl = self._clean(lifecycle_id)
        if not wl:
            return None
        row = fetchone_dict(
            self._session,
            f"""
            SELECT id::text AS id,
                   tenant_id::text AS tenant_id,
                   event_type,
                   workflow_lifecycle_id::text AS workflow_lifecycle_id,
                   created_at,
                   updated_at
            FROM {self.TABLE_NAME}
            WHERE trim(both workflow_lifecycle_id::text) = trim(both CAST(:wl AS text))
            ORDER BY created_at DESC
            LIMIT 1
            """,
            {"wl": wl},
        )
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "tenant_id": str(row["tenant_id"]),
            "event_type": row["event_type"],
            "workflow_lifecycle_id": str(row["workflow_lifecycle_id"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
