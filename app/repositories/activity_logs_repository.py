"""Insert rows into ``activity_logs`` (workflow audit trail)."""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg.types.json import Json

from app.core.config import settings


class ActivityLogsRepository:
    TABLE_NAME = "activity_logs"
    TENDERS_TABLE = "tenders"

    def insert(self, row: dict[str, Any]) -> str:
        """Insert one activity row; return ``activity_logs.id``."""

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        tenant_id,
                        workflow_lifecycle_id,
                        workflow_run_id,
                        activity_type,
                        description,
                        from_status,
                        to_status,
                        from_sub_status,
                        to_sub_status,
                        actor_type,
                        actor_id,
                        metadata
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::uuid,
                        %s
                    )
                    RETURNING id::text
                    """,
                    (
                        row["tenant_id"],
                        row.get("workflow_lifecycle_id"),
                        row.get("workflow_run_id"),
                        row["activity_type"],
                        row.get("description"),
                        row.get("from_status"),
                        row.get("to_status"),
                        row.get("from_sub_status"),
                        row.get("to_sub_status"),
                        row.get("actor_type"),
                        row.get("actor_id"),
                        Json(row.get("metadata") or {}),
                    ),
                )
                out = cur.fetchone()
            conn.commit()
        finally:
            conn.close()

        if not out or not out[0]:
            raise RuntimeError("activity_logs insert returned no id")
        return str(out[0])

    def apply_tender_processing_with_status_change_log(
        self,
        *,
        tenant_id: str,
        tender_id: str,
        log_row: dict[str, Any],
    ) -> None:
        """
        In one transaction: set ``tenders.status`` to processing and insert status_change log.
        """

        conn = psycopg.connect(settings.DATABASE_URL)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self.TENDERS_TABLE}
                    SET status = %s, updated_at = NOW()
                    WHERE id = %s::uuid AND tenant_id = %s::uuid
                    """,
                    (
                        log_row.get("tender_status", "processing"),
                        tender_id,
                        tenant_id,
                    ),
                )
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        tenant_id,
                        workflow_lifecycle_id,
                        workflow_run_id,
                        activity_type,
                        description,
                        from_status,
                        to_status,
                        from_sub_status,
                        to_sub_status,
                        actor_type,
                        actor_id,
                        metadata
                    )
                    VALUES (
                        %s::uuid,
                        %s::uuid,
                        %s::uuid,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s::uuid,
                        %s
                    )
                    """,
                    (
                        log_row["tenant_id"],
                        log_row.get("workflow_lifecycle_id"),
                        log_row.get("workflow_run_id"),
                        log_row["activity_type"],
                        log_row.get("description"),
                        log_row.get("from_status"),
                        log_row.get("to_status"),
                        log_row.get("from_sub_status"),
                        log_row.get("to_sub_status"),
                        log_row.get("actor_type"),
                        log_row.get("actor_id"),
                        Json(log_row.get("metadata") or {}),
                    ),
                )
            conn.commit()
        finally:
            conn.close()
