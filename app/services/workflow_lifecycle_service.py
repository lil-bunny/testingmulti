from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

import psycopg

from app.core.config import settings
from app.models.status import (
    StatusType,
    StatusSubType
)
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid


@dataclass(frozen=True)
class LifecycleResolution:
    """Result of lifecycle resolution."""

    workflow_lifecycle_id: str
    existed: bool


class WorkflowLifecycleService:
    """
    Resolve or create workflow lifecycle identity from business correlation keys.

    NOTE:
    - This service expects a `workflow_lifecycles` table to exist.
    - It is intentionally added as a standalone building block and is not yet
      wired into existing execution paths.
    """

    TABLE_NAME = "workflow_lifecycles"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

    @staticmethod
    def _clean(value: Any) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _extract_thread_id(payload: dict[str, Any]) -> Optional[str]:
        # `thread_id` here refers to the external email conversation thread id.
        return WorkflowLifecycleService._clean(payload.get("thread_id"))

    @staticmethod
    def _extract_shipment_id(payload: dict[str, Any]) -> Optional[str]:
        return WorkflowLifecycleService._clean(payload.get("shipment_id"))

    @staticmethod
    def _extract_tender_id(payload: dict[str, Any]) -> Optional[str]:
        raw = WorkflowLifecycleService._clean(payload.get("tender_id"))
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            return None

    def _find_existing_lifecycle_id(
        self,
        cur,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: Optional[str],
        thread_id: Optional[str],
        shipment_id: Optional[str],
    ) -> Optional[str]:
        if tender_id:
            cur.execute(
                f"""
                SELECT id
                FROM {self.TABLE_NAME}
                WHERE tenant_id = %s
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

        # Priority order: thread (email thread id) -> shipment.
        # ``load_id`` is not persisted on ``workflow_lifecycles``; correlate via shipment when needed.
        for field_name, field_value in (
            ("email_thread_id", thread_id),
            ("shipment_id", shipment_id),
        ):
            if not field_value:
                continue
            cur.execute(
                f"""
                SELECT id
                FROM {self.TABLE_NAME}
                WHERE tenant_id = %s
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

    def _insert_lifecycle(
        self,
        cur,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
        tender_id: Optional[str],
        thread_id: Optional[str],
        shipment_id: Optional[str],
    ) -> None:
        cur.execute(
            f"""
            INSERT INTO {self.TABLE_NAME} (
                id,
                tenant_id,
                workflow_name,
                tender_id,
                email_thread_id,
                shipment_id
            ) VALUES (%s, %s, %s, %s::uuid, %s, %s)
            """,
            (
                lifecycle_id,
                tenant_id,
                workflow_name,
                tender_id,
                thread_id,
                shipment_id,
            ),
        )

    def _update_lifecycle_keys(
        self,
        cur,
        *,
        lifecycle_id: str,
        tender_id: Optional[str],
        thread_id: Optional[str],
        shipment_id: Optional[str],
    ) -> None:
        cur.execute(
            f"""
            UPDATE {self.TABLE_NAME}
            SET
                tender_id = COALESCE(%s::uuid, tender_id),
                email_thread_id = COALESCE(%s, email_thread_id),
                shipment_id = COALESCE(%s, shipment_id),
                updated_at = NOW()
            WHERE id = %s
            """,
            (tender_id, thread_id, shipment_id, lifecycle_id),
        )

    def read_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        load_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        """Read-only lookup. Returns lifecycle data if found, no row creation.

        ``load_id`` is accepted for API compatibility but lifecycles are not keyed by ``load_id`` in the DB.
        """
        tid_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tid_raw) if tid_raw else None
        if not tid or not wn:
            return {"found": False}

        t = self._clean(thread_id)
        s = self._clean(shipment_id)
        tender = self._extract_tender_id({"tender_id": tender_id}) if tender_id else None

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                lifecycle_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=tid,
                    workflow_name=wn,
                    tender_id=tender,
                    thread_id=t,
                    shipment_id=s,
                )
                if not lifecycle_id:
                    return {"found": False}

                cur.execute(
                    f"""
                    SELECT shipment_id, email_thread_id, workflow_name, tender_id::text
                    FROM {self.TABLE_NAME}
                    WHERE id = %s
                    """,
                    (lifecycle_id,),
                )
                row = cur.fetchone()
                if not row:
                    return {"found": False}

                return {
                    "found": True,
                    "lifecycle_id": lifecycle_id,
                    "shipment_id": row[0] or "",
                    "load_id": "",
                    "email_thread_id": row[1] or "",
                    "workflow_name": row[2] or "",
                    "tender_id": row[3] or "",
                }
        finally:
            conn.close()

    def update_lifecycle_keys(
        self,
        *,
        lifecycle_id: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        load_id: str | None = None,
        tender_id: str | None = None,
    ) -> None:
        """Backfill lifecycle keys onto an existing lifecycle row. ``load_id`` is ignored (not stored)."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                self._update_lifecycle_keys(
                    cur,
                    lifecycle_id=lifecycle_id,
                    tender_id=self._extract_tender_id({"tender_id": tender_id})
                    if tender_id
                    else None,
                    thread_id=self._clean(thread_id),
                    shipment_id=self._clean(shipment_id),
                )
            conn.commit()
        finally:
            conn.close()

    def check_lifecycle_exists(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str | None = None,
        load_id: str | None = None,
        thread_id: str | None = None,
        tender_id: str | None = None,
    ) -> dict:
        """Check if a lifecycle row exists for given keys. ``load_id`` is ignored."""
        tenant_raw = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        tid = resolve_graph_tenant_to_uuid(tenant_raw) if tenant_raw else None
        if not tid or not wn:
            return {"exists": False}

        tender = self._extract_tender_id({"tender_id": tender_id}) if tender_id else None

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                lifecycle_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=tid,
                    workflow_name=wn,
                    tender_id=tender,
                    thread_id=self._clean(thread_id),
                    shipment_id=self._clean(shipment_id),
                )
                if lifecycle_id:
                    return {"exists": True, "lifecycle_id": lifecycle_id}
                return {"exists": False}
        finally:
            conn.close()

    def resolve_or_create_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        payload: dict[str, Any],
    ) -> LifecycleResolution:
        """
        Resolve existing lifecycle id by correlation keys or create a new row.

        Returns:
            LifecycleResolution(workflow_lifecycle_id=<id>, existed=<bool>)
        """
        tenant_id_clean = self._clean(tenant_id)
        workflow_name_clean = self._clean(workflow_name)
        if not tenant_id_clean or not workflow_name_clean:
            raise ValueError("tenant_id and workflow_name are required")

        db_tenant_id = resolve_graph_tenant_to_uuid(tenant_id_clean)
        if not db_tenant_id:
            raise ValueError(
                f"No matching tenants row for tenant_id={tenant_id_clean!r} "
                "(expected UUID or tenants.slug matching TENANT_CONFIGS key)"
            )

        tender_id = self._extract_tender_id(payload)
        thread_id = self._extract_thread_id(payload)
        shipment_id = self._extract_shipment_id(payload)

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                existing_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=db_tenant_id,
                    workflow_name=workflow_name_clean,
                    tender_id=tender_id,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                )
                if existing_id:
                    self._update_lifecycle_keys(
                        cur,
                        lifecycle_id=existing_id,
                        tender_id=tender_id,
                        thread_id=thread_id,
                        shipment_id=shipment_id,
                    )
                    conn.commit()
                    return LifecycleResolution(
                        workflow_lifecycle_id=existing_id,
                        existed=True,
                    )

                new_id = str(uuid.uuid4())
                self._insert_lifecycle(
                    cur,
                    lifecycle_id=new_id,
                    tenant_id=db_tenant_id,
                    workflow_name=workflow_name_clean,
                    tender_id=tender_id,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                )
                conn.commit()
                return LifecycleResolution(
                    workflow_lifecycle_id=new_id,
                    existed=False,
                )
        finally:
            conn.close()

    def read_lifecycle_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return tenant_id, workflow_name, status, sub_status, email_thread_id for a lifecycle PK."""
        lid = self._clean(lifecycle_id)
        if not lid:
            return None
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT tenant_id::text, workflow_name, status, sub_status,
                           email_thread_id, tender_id::text
                    FROM {self.TABLE_NAME}
                    WHERE id = %s::uuid
                    """,
                    (lid,),
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
                }
        finally:
            conn.close()


    def update_lifecycle_status(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        """
        Update lifecycle status fields.

        - ``None`` means "leave unchanged".
        - Uses enum types internally.
        - Serializes enums only at DB boundary.
        - Returns whether any row was updated.
        """

        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")

        updates: list[str] = []
        params: list[Any] = []

        if status is not None:
            updates.append("status = %s")
            params.append(status.value)

        if sub_status is not None:
            updates.append("sub_status = %s")
            params.append(sub_status.value)

        if not updates:
            return False

        updates.append("updated_at = NOW()")

        params.append(lid)

        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET {", ".join(updates)}
            WHERE id = %s::uuid
        """

        conn = self._conn()

        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                updated = cur.rowcount > 0

            conn.commit()
            return updated

        finally:
            conn.close()

    def update_lifecycle_sub_status(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        """Set ``sub_status`` unconditionally. Returns whether a row was updated."""

        lid = self._clean(lifecycle_id)
        if not lid:
            raise ValueError("lifecycle_id required")

        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET
                sub_status = %s,
                updated_at = NOW()
            WHERE id = %s::uuid
        """

        conn = self._conn()

        try:
            with conn.cursor() as cur:
                cur.execute(sql, (new_sub_status.value, lid))
                updated = cur.rowcount > 0

            conn.commit()
            return updated

        finally:
            conn.close()