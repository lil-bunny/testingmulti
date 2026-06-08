"""Read/write ``communications`` (channel message log)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import execute_scalar, fetchall_dicts, jsonb_param
from app.models.workflow_run_event_type import WorkflowRunEventType


class CommunicationsRepository:
    TABLE_NAME = "communications"

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_email_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return email communications for a thread, oldest first."""
        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT
                id::text AS id,
                direction::text AS direction,
                content,
                metadata,
                created_at
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND thread_id = :thread_id
              AND channel = 'email'::communication_channel
            ORDER BY created_at ASC
            LIMIT :limit
            """,
            {"tenant_id": tenant_id, "thread_id": thread_id, "limit": limit},
            json_keys=frozenset({"metadata"}),
        )

        out: list[dict[str, Any]] = []
        for row in rows:
            meta = row.get("metadata")
            if meta is None:
                meta = {}
            elif not isinstance(meta, dict):
                meta = dict(meta)
            out.append(
                {
                    "id": row["id"],
                    "direction": row["direction"],
                    "content": row["content"],
                    "metadata": meta,
                    "created_at": row["created_at"],
                }
            )
        return out

    def insert(self, row: dict[str, Any]) -> str | None:
        """
        Insert one communication row; return ``communications.id``.

        When ``external_id`` is set, duplicate ``(tenant_id, external_id)`` rows are
        skipped (``ON CONFLICT DO NOTHING``) and this returns ``None``.
        """
        row_id = execute_scalar(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                channel,
                direction,
                external_id,
                thread_id,
                content,
                metadata,
                workflow_run_id
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:channel AS communication_channel),
                CAST(:direction AS communication_direction),
                :external_id,
                :thread_id,
                :content,
                CAST(:metadata AS jsonb),
                CAST(:workflow_run_id AS uuid)
            )
            ON CONFLICT (tenant_id, external_id)
            WHERE external_id IS NOT NULL
            DO NOTHING
            RETURNING id::text
            """,
            {
                "tenant_id": row["tenant_id"],
                "channel": row["channel"],
                "direction": row["direction"],
                "external_id": row.get("external_id"),
                "thread_id": row.get("thread_id"),
                "content": row.get("content"),
                "metadata": jsonb_param(row.get("metadata") or {}),
                "workflow_run_id": row.get("workflow_run_id"),
            },
        )
        if not row_id:
            return None
        return str(row_id)

    def find_id_by_tenant_and_external_id(
        self,
        *,
        tenant_id: str,
        external_id: str,
    ) -> str | None:
        """Return ``communications.id`` for a tenant-scoped Unipile ``email_id``."""
        row_id = execute_scalar(
            self._session,
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND external_id = :external_id
            LIMIT 1
            """,
            {"tenant_id": tenant_id, "external_id": external_id},
        )
        return str(row_id) if row_id else None

    def link_workflow_run(
        self,
        *,
        communication_id: str,
        workflow_run_id: str,
    ) -> bool:
        """Set ``workflow_run_id`` on comm when unlinked or already same run (idempotent)."""
        existing = execute_scalar(
            self._session,
            f"""
            SELECT workflow_run_id::text
            FROM {self.TABLE_NAME}
            WHERE id = CAST(:communication_id AS uuid)
            """,
            {"communication_id": communication_id},
        )
        if existing and str(existing).strip() == str(workflow_run_id).strip():
            return True
        rowcount = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET workflow_run_id = CAST(:workflow_run_id AS uuid)
                WHERE id = CAST(:communication_id AS uuid)
                  AND workflow_run_id IS NULL
                """
            ),
            {
                "communication_id": communication_id,
                "workflow_run_id": workflow_run_id,
            },
        ).rowcount
        return rowcount > 0

    def link_workflow_run_to_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_run_id: str,
    ) -> int:
        """Patch ``workflow_run_id`` on all unlinked comms for a tenant thread."""
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET workflow_run_id = CAST(:workflow_run_id AS uuid)
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND thread_id = :thread_id
                  AND workflow_run_id IS NULL
                """
            ),
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_run_id": workflow_run_id,
            },
        )
        return int(result.rowcount or 0)

    def find_inbound_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.EMAIL_RECEIVED,
    ) -> str | None:
        """``communications.thread_id`` from the latest linked run for ``anchor_event_type``."""
        thread_id = execute_scalar(
            self._session,
            """
            SELECT c.thread_id
            FROM communications c
            JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            WHERE wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
              AND wr.tenant_id = CAST(:tenant_id AS uuid)
              AND wr.event_type = :anchor_event_type
              AND c.thread_id IS NOT NULL
              AND TRIM(c.thread_id) <> ''
            ORDER BY c.created_at DESC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "workflow_lifecycle_id": workflow_lifecycle_id,
                "anchor_event_type": anchor_event_type,
            },
        )
        if not thread_id:
            return None
        return str(thread_id).strip() or None

    def resolve_lifecycle_id_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_name: str = "load_tendering",
    ) -> str | None:
        """Earliest patched comm on thread → ``workflow_runs`` → lifecycle (ack ingress)."""
        lifecycle_id = execute_scalar(
            self._session,
            """
            SELECT wr.workflow_lifecycle_id::text
            FROM communications c
            JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.thread_id = :thread_id
              AND c.workflow_run_id IS NOT NULL
              AND wl.workflow_name = :workflow_name
            ORDER BY c.created_at ASC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_name": workflow_name,
            },
        )
        if not lifecycle_id:
            return None
        return str(lifecycle_id).strip() or None

    def is_thread_linked_to_lifecycle(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
    ) -> bool:
        """True when this thread already has a patched comm for the lifecycle (idempotency)."""
        linked = execute_scalar(
            self._session,
            """
            SELECT EXISTS (
                SELECT 1
                FROM communications c
                JOIN workflow_runs wr ON wr.id = c.workflow_run_id
                WHERE c.tenant_id = CAST(:tenant_id AS uuid)
                  AND c.thread_id = :thread_id
                  AND wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
                  AND wr.event_type = :anchor_event_type
            )
            """,
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_lifecycle_id": workflow_lifecycle_id,
                "anchor_event_type": anchor_event_type,
            },
        )
        return bool(linked)

    def find_linked_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
    ) -> str | None:
        """Thread id already linked to lifecycle via ``anchor_event_type`` run (conflict guard)."""
        thread_id = execute_scalar(
            self._session,
            """
            SELECT c.thread_id
            FROM communications c
            JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
              AND wr.event_type = :anchor_event_type
              AND c.thread_id IS NOT NULL
              AND TRIM(c.thread_id) <> ''
            ORDER BY c.created_at ASC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "workflow_lifecycle_id": workflow_lifecycle_id,
                "anchor_event_type": anchor_event_type,
            },
        )
        if not thread_id:
            return None
        return str(thread_id).strip() or None
