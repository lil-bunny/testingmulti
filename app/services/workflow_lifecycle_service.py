from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Optional

import psycopg

from app.core.config import settings


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
    def _extract_load_id(payload: dict[str, Any]) -> Optional[str]:
        return WorkflowLifecycleService._clean(payload.get("load_id"))

    def _find_existing_lifecycle_id(
        self,
        cur,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: Optional[str],
        shipment_id: Optional[str],
        load_id: Optional[str],
    ) -> Optional[str]:
        # Priority order: thread (email thread id) -> shipment -> load.
        for field_name, field_value in (
            ("email_thread_id", thread_id),
            ("shipment_id", shipment_id),
            ("load_id", load_id),
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
        thread_id: Optional[str],
        shipment_id: Optional[str],
        load_id: Optional[str],
    ) -> None:
        cur.execute(
            f"""
            INSERT INTO {self.TABLE_NAME} (
                id,
                tenant_id,
                workflow_name,
                email_thread_id,
                shipment_id,
                load_id
            ) VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (
                lifecycle_id,
                tenant_id,
                workflow_name,
                thread_id,
                shipment_id,
                load_id,
            ),
        )

    def _update_lifecycle_keys(
        self,
        cur,
        *,
        lifecycle_id: str,
        thread_id: Optional[str],
        shipment_id: Optional[str],
        load_id: Optional[str],
    ) -> None:
        cur.execute(
            f"""
            UPDATE {self.TABLE_NAME}
            SET
                email_thread_id = COALESCE(%s, email_thread_id),
                shipment_id = COALESCE(%s, shipment_id),
                load_id = COALESCE(%s, load_id),
                updated_at = NOW()
            WHERE id = %s
            """,
            (thread_id, shipment_id, load_id, lifecycle_id),
        )

    def read_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
        load_id: str | None = None,
    ) -> dict:
        """Read-only lookup. Returns lifecycle data if found, no row creation."""
        tid = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        if not tid or not wn:
            return {"found": False}

        t = self._clean(thread_id)
        s = self._clean(shipment_id)
        l = self._clean(load_id)

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                lifecycle_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=tid,
                    workflow_name=wn,
                    thread_id=t,
                    shipment_id=s,
                    load_id=l,
                )
                if not lifecycle_id:
                    return {"found": False}

                cur.execute(
                    f"""
                    SELECT shipment_id, load_id, email_thread_id, workflow_name
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
                    "load_id": row[1] or "",
                    "email_thread_id": row[2] or "",
                    "workflow_name": row[3] or "",
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
    ) -> None:
        """Backfill lifecycle keys onto an existing lifecycle row."""
        conn = self._conn()
        try:
            with conn.cursor() as cur:
                self._update_lifecycle_keys(
                    cur,
                    lifecycle_id=lifecycle_id,
                    thread_id=self._clean(thread_id),
                    shipment_id=self._clean(shipment_id),
                    load_id=self._clean(load_id),
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
    ) -> dict:
        """Check if a lifecycle row exists for given keys."""
        tid = self._clean(tenant_id)
        wn = self._clean(workflow_name)
        if not tid or not wn:
            return {"exists": False}

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                lifecycle_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=tid,
                    workflow_name=wn,
                    thread_id=self._clean(thread_id),
                    shipment_id=self._clean(shipment_id),
                    load_id=self._clean(load_id),
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

        thread_id = self._extract_thread_id(payload)
        shipment_id = self._extract_shipment_id(payload)
        load_id = self._extract_load_id(payload)

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                existing_id = self._find_existing_lifecycle_id(
                    cur,
                    tenant_id=tenant_id_clean,
                    workflow_name=workflow_name_clean,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                    load_id=load_id,
                )
                if existing_id:
                    self._update_lifecycle_keys(
                        cur,
                        lifecycle_id=existing_id,
                        thread_id=thread_id,
                        shipment_id=shipment_id,
                        load_id=load_id,
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
                    tenant_id=tenant_id_clean,
                    workflow_name=workflow_name_clean,
                    thread_id=thread_id,
                    shipment_id=shipment_id,
                    load_id=load_id,
                )
                conn.commit()
                return LifecycleResolution(
                    workflow_lifecycle_id=new_id,
                    existed=False,
                )
        finally:
            conn.close()
