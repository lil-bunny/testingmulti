"""Reads/writes for ``workflow_lifecycles``."""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from app.core.config import settings
from app.models.status import StatusSubType, StatusType


class WorkflowLifecyclesRepository:
    TABLE_NAME = "workflow_lifecycles"

    @staticmethod
    def _conn() -> psycopg.Connection:
        return psycopg.connect(settings.DATABASE_URL)

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

    def find_id_by_load_id(
        self,
        cur: psycopg.Cursor,
        *,
        tenant_id: str,
        workflow_name: str,
        load_id: str,
    ) -> str | None:
        cur.execute(
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = %s::uuid
              AND workflow_name = %s
              AND load_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (tenant_id, workflow_name, load_id),
        )
        row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
        return None

    def find_existing_lifecycle_id(
        self,
        cur: psycopg.Cursor,
        *,
        tenant_id: str,
        workflow_name: str,
        load_id: str | None = None,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        """
        Resolve lifecycle PK by correlation keys.

        Priority: ``load_id`` → ``tender_id`` → ``email_thread_id`` → ``shipment_id``.
        """
        if load_id:
            found = self.find_id_by_load_id(
                cur,
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                load_id=load_id,
            )
            if found:
                return found

        if tender_id:
            cur.execute(
                f"""
                SELECT id::text
                FROM {self.TABLE_NAME}
                WHERE tenant_id = %s::uuid
                  AND workflow_name = %s
                  AND tender_id = %s::uuid
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tenant_id, workflow_name, tender_id),
            )
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])

        for field_name, field_value in (
            ("email_thread_id", thread_id),
            ("shipment_id", shipment_id),
        ):
            if not field_value:
                continue
            cur.execute(
                f"""
                SELECT id::text
                FROM {self.TABLE_NAME}
                WHERE tenant_id = %s::uuid
                  AND workflow_name = %s
                  AND {field_name} = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (tenant_id, workflow_name, field_value),
            )
            row = cur.fetchone()
            if row and row[0]:
                return str(row[0])
        return None

    def insert_lifecycle(
        self,
        cur: psycopg.Cursor,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
        load_id: str | None = None,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> None:
        cur.execute(
            f"""
            INSERT INTO {self.TABLE_NAME} (
                id,
                tenant_id,
                workflow_name,
                load_id,
                tender_id,
                email_thread_id,
                shipment_id
            ) VALUES (%s::uuid, %s::uuid, %s, %s, %s::uuid, %s, %s)
            """,
            (
                lifecycle_id,
                tenant_id,
                workflow_name,
                load_id,
                tender_id,
                thread_id,
                shipment_id,
            ),
        )

    def read_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return lifecycle row fields for a PK."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT tenant_id::text, workflow_name, status::text, sub_status::text,
                           email_thread_id, tender_id::text, load_id
                    FROM {self.TABLE_NAME}
                    WHERE id = %s::uuid
                    """,
                    (lifecycle_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "tenant_id": row[0],
                    "workflow_name": row[1],
                    "status": row[2],
                    "sub_status": row[3],
                    "email_thread_id": row[4],
                    "tender_id": row[5] or "",
                    "load_id": row[6] or "",
                }
        finally:
            conn.close()

    def read_correlation_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Shipment/thread/load_id fields for ``read_lifecycle`` responses."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT shipment_id::text, email_thread_id, workflow_name, load_id
                    FROM {self.TABLE_NAME}
                    WHERE id = %s::uuid
                    """,
                    (lifecycle_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "shipment_id": row[0] or "",
                    "email_thread_id": row[1] or "",
                    "workflow_name": row[2] or "",
                    "load_id": row[3] or "",
                }
        finally:
            conn.close()

    def find_existing_lifecycle_id_tx(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        load_id: str | None = None,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                return self.find_existing_lifecycle_id(
                    cur,
                    tenant_id=tenant_id,
                    workflow_name=workflow_name,
                    load_id=load_id,
                    tender_id=tender_id,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                )
        finally:
            conn.close()

    def resolve_or_create(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        load_id: str | None = None,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> tuple[str, bool]:
        """Return ``(lifecycle_id, existed)``."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                existing_id = self.find_existing_lifecycle_id(
                    cur,
                    tenant_id=tenant_id,
                    workflow_name=workflow_name,
                    load_id=load_id,
                    tender_id=tender_id,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                )
                if existing_id:
                    conn.commit()
                    return existing_id, True

                new_id = str(uuid.uuid4())
                self.insert_lifecycle(
                    cur,
                    lifecycle_id=new_id,
                    tenant_id=tenant_id,
                    workflow_name=workflow_name,
                    load_id=load_id,
                    tender_id=tender_id,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                )
                conn.commit()
                return new_id, False
        finally:
            conn.close()

    def set_email_thread_id_tx(
        self,
        *,
        lifecycle_id: str,
        email_thread_id: str,
    ) -> bool:
        conn = self._conn()
        try:
            updated = self.update_email_thread_id(
                conn,
                lifecycle_id=lifecycle_id,
                email_thread_id=email_thread_id,
            )
            conn.commit()
            return updated
        finally:
            conn.close()

    def update_lifecycle_status_tx(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        conn = self._conn()
        try:
            updated = self.update_status(
                conn,
                lifecycle_id=lifecycle_id,
                status=status,
                sub_status=sub_status,
            )
            conn.commit()
            return updated
        finally:
            conn.close()

    def update_lifecycle_sub_status_tx(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE {self.TABLE_NAME}
                    SET
                        sub_status = %s::lifecycle_sub_status,
                        updated_at = NOW()
                    WHERE id = %s::uuid
                    """,
                    (new_sub_status.value, lifecycle_id),
                )
                updated = cur.rowcount > 0
            conn.commit()
            return updated
        finally:
            conn.close()
