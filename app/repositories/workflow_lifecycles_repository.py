"""Reads/writes for ``workflow_lifecycles``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.status import StatusSubType, StatusType


class WorkflowLifecyclesRepository:
    TABLE_NAME = "workflow_lifecycles"

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_for_update(
        self,
        *,
        lifecycle_id: str,
    ) -> dict[str, Any] | None:
        row = self._session.execute(
            text(
                f"""
                SELECT status::text, sub_status::text, tenant_id::text, workflow_name
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:lifecycle_id AS uuid)
                FOR UPDATE
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
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
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        updates: list[str] = []
        params: dict[str, Any] = {"lifecycle_id": lifecycle_id}

        if status is not None:
            updates.append("status = CAST(:status AS lifecycle_status)")
            params["status"] = status.value

        if sub_status is not None:
            updates.append("sub_status = CAST(:sub_status AS lifecycle_sub_status)")
            params["sub_status"] = sub_status.value

        if not updates:
            return False

        updates.append("updated_at = NOW()")
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET {", ".join(updates)}
            WHERE id = CAST(:lifecycle_id AS uuid)
        """
        result = self._session.execute(text(sql), params)
        return result.rowcount > 0

    def update_email_thread_id(
        self,
        *,
        lifecycle_id: str,
        email_thread_id: str,
    ) -> bool:
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET email_thread_id = :email_thread_id, updated_at = NOW()
                WHERE id = CAST(:lifecycle_id AS uuid)
                """
            ),
            {
                "email_thread_id": email_thread_id,
                "lifecycle_id": lifecycle_id,
            },
        )
        return result.rowcount > 0

    def find_id_by_load_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        load_id: str,
    ) -> str | None:
        row = self._session.execute(
            text(
                f"""
                SELECT id::text
                FROM {self.TABLE_NAME}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND workflow_name = :workflow_name
                  AND load_id = :load_id
                ORDER BY updated_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "load_id": load_id,
            },
        ).first()
        if row and row[0]:
            return str(row[0])
        return None

    def find_existing_lifecycle_id(
        self,
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
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                load_id=load_id,
            )
            if found:
                return found

        if tender_id:
            row = self._session.execute(
                text(
                    f"""
                    SELECT id::text
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND workflow_name = :workflow_name
                      AND tender_id = CAST(:tender_id AS uuid)
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "workflow_name": workflow_name,
                    "tender_id": tender_id,
                },
            ).first()
            if row and row[0]:
                return str(row[0])

        for field_name, field_value in (
            ("email_thread_id", thread_id),
            ("shipment_id", shipment_id),
        ):
            if not field_value:
                continue
            row = self._session.execute(
                text(
                    f"""
                    SELECT id::text
                    FROM {self.TABLE_NAME}
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND workflow_name = :workflow_name
                      AND {field_name} = :field_value
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "workflow_name": workflow_name,
                    "field_value": field_value,
                },
            ).first()
            if row and row[0]:
                return str(row[0])
        return None

    def insert_lifecycle(
        self,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
        load_id: str | None = None,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> None:
        self._session.execute(
            text(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    id,
                    tenant_id,
                    workflow_name,
                    load_id,
                    tender_id,
                    email_thread_id,
                    shipment_id
                ) VALUES (
                    CAST(:lifecycle_id AS uuid),
                    CAST(:tenant_id AS uuid),
                    :workflow_name,
                    :load_id,
                    CAST(:tender_id AS uuid),
                    :thread_id,
                    :shipment_id
                )
                """
            ),
            {
                "lifecycle_id": lifecycle_id,
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "load_id": load_id,
                "tender_id": tender_id,
                "thread_id": thread_id,
                "shipment_id": shipment_id,
            },
        )

    def read_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return lifecycle row fields for a PK."""
        row = self._session.execute(
            text(
                f"""
                SELECT tenant_id::text, workflow_name, status::text, sub_status::text,
                       email_thread_id, tender_id::text, load_id
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:lifecycle_id AS uuid)
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
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

    def read_correlation_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Shipment/thread/load_id fields for ``read_lifecycle`` responses."""
        row = self._session.execute(
            text(
                f"""
                SELECT shipment_id::text, email_thread_id, workflow_name, load_id
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:lifecycle_id AS uuid)
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return {
            "shipment_id": row[0] or "",
            "email_thread_id": row[1] or "",
            "workflow_name": row[2] or "",
            "load_id": row[3] or "",
        }

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
        return self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            load_id=load_id,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )

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
        """Return ``(lifecycle_id, existed)`` without committing."""
        existing_id = self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            load_id=load_id,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )
        if existing_id:
            return existing_id, True

        new_id = str(uuid.uuid4())
        self.insert_lifecycle(
            lifecycle_id=new_id,
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            load_id=load_id,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )
        return new_id, False

    def set_email_thread_id_tx(
        self,
        *,
        lifecycle_id: str,
        email_thread_id: str,
    ) -> bool:
        return self.update_email_thread_id(
            lifecycle_id=lifecycle_id,
            email_thread_id=email_thread_id,
        )

    def update_lifecycle_status_tx(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        return self.update_status(
            lifecycle_id=lifecycle_id,
            status=status,
            sub_status=sub_status,
        )

    def update_lifecycle_sub_status_tx(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET
                    sub_status = CAST(:sub_status AS lifecycle_sub_status),
                    updated_at = NOW()
                WHERE id = CAST(:lifecycle_id AS uuid)
                """
            ),
            {
                "sub_status": new_sub_status.value,
                "lifecycle_id": lifecycle_id,
            },
        )
        return result.rowcount > 0
