"""Insert rows into ``communications`` (channel message log)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


class CommunicationsRepository:
    TABLE_NAME = "communications"

    def insert(self, row: dict[str, Any]) -> str:
        """Insert one communication row; return ``communications.id``."""

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
            raise RuntimeError("communications insert returned no id")
        return str(out[0])
