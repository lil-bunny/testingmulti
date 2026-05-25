"""Transactional reads/writes for ``workflow_lifecycles``."""

from __future__ import annotations

from typing import Any

import psycopg

from app.models.status import StatusSubType, StatusType


class WorkflowLifecyclesRepository:
    TABLE_NAME = "workflow_lifecycles"

    def get_for_update(
        self,
        conn: psycopg.Connection,
        *,
        lifecycle_id: str,
    ) -> dict[str, Any] | None:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT status::text, sub_status::text, tenant_id::text, workflow_name
                FROM {self.TABLE_NAME}
                WHERE id = %s::uuid
                FOR UPDATE
                """,
                (lifecycle_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {
                "status": row[0],
                "sub_status": row[1],
                "tenant_id": row[2],
                "workflow_name": row[3],
            }

    def update_status(
        self,
        conn: psycopg.Connection,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        updates: list[str] = []
        params: list[Any] = []

        if status is not None:
            updates.append("status = %s::lifecycle_status")
            params.append(status.value)

        if sub_status is not None:
            updates.append("sub_status = %s::lifecycle_sub_status")
            params.append(sub_status.value)

        if not updates:
            return False

        updates.append("updated_at = NOW()")
        params.append(lifecycle_id)

        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET {", ".join(updates)}
            WHERE id = %s::uuid
        """
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount > 0

    def update_email_thread_id(
        self,
        conn: psycopg.Connection,
        *,
        lifecycle_id: str,
        email_thread_id: str,
    ) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self.TABLE_NAME}
                SET email_thread_id = %s, updated_at = NOW()
                WHERE id = %s::uuid
                """,
                (email_thread_id, lifecycle_id),
            )
            return cur.rowcount > 0
