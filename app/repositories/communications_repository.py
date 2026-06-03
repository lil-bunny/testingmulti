"""Read/write ``communications`` (channel message log)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import execute_scalar, fetchall_dicts


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
                :metadata,
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
                "metadata": row.get("metadata") or {},
                "workflow_run_id": row.get("workflow_run_id"),
            },
        )
        if not row_id:
            return None
        return str(row_id)
