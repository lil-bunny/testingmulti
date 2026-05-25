"""Read/write ``communications`` (channel message log)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


class CommunicationsRepository:
    TABLE_NAME = "communications"

    def list_email_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return email communications for a thread, oldest first."""
        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        id::text,
                        direction::text,
                        content,
                        metadata,
                        created_at
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = %s::uuid
                      AND thread_id = %s
                      AND channel = 'email'::communication_channel
                    ORDER BY created_at ASC
                    LIMIT %s
                    """,
                    (tenant_id, thread_id, limit),
                )
                rows = cur.fetchall()
        finally:
            conn.close()

        out: list[dict[str, Any]] = []
        for row in rows:
            meta = row[3]
            if meta is None:
                meta = {}
            elif not isinstance(meta, dict):
                meta = dict(meta)
            out.append(
                {
                    "id": row[0],
                    "direction": row[1],
                    "content": row[2],
                    "metadata": meta,
                    "created_at": row[4],
                }
            )
        return out

    def insert(self, row: dict[str, Any]) -> str | None:
        """
        Insert one communication row; return ``communications.id``.

        When ``external_id`` is set, duplicate ``(tenant_id, external_id)`` rows are
        skipped (``ON CONFLICT DO NOTHING``) and this returns ``None``.
        """
        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        tenant_id,
                        channel,
                        direction,
                        external_id,
                        thread_id,
                        content,
                        metadata
                    )
                    VALUES (
                        %s::uuid,
                        %s::communication_channel,
                        %s::communication_direction,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                    ON CONFLICT (tenant_id, external_id)
                    WHERE external_id IS NOT NULL
                    DO NOTHING
                    RETURNING id::text
                    """,
                    (
                        row["tenant_id"],
                        row["channel"],
                        row["direction"],
                        row.get("external_id"),
                        row.get("thread_id"),
                        row.get("content"),
                        Json(row.get("metadata") or {}),
                    ),
                )
                out = cur.fetchone()
            conn.commit()
        finally:
            conn.close()

        if not out or not out[0]:
            return None
        return str(out[0])
