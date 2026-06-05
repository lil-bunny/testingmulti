"""Reads/writes for ``workflow_lifecycles``."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.status import StatusSubType, StatusType

_WHERE_LIFECYCLE_ID = """
    WHERE id = CAST(:lifecycle_id AS uuid)
"""

_WHERE_TENANT_WORKFLOW = """
    WHERE tenant_id = CAST(:tenant_id AS uuid)
      AND workflow_name = :workflow_name
"""

_LOOKUP_ORDER_LIMIT = """
    ORDER BY updated_at DESC
    LIMIT 1
"""


class WorkflowLifecyclesRepository:
    TABLE_NAME = "workflow_lifecycles"

    def __init__(self, session: Session) -> None:
        self._session = session

    def _fetch_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        extra_predicate: str,
        extra_params: dict[str, Any],
    ) -> str | None:
        sql = f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            {_WHERE_TENANT_WORKFLOW}
              {extra_predicate}
            {_LOOKUP_ORDER_LIMIT}
        """
        params = {
            "tenant_id": tenant_id,
            "workflow_name": workflow_name,
            **extra_params,
        }
        row = self._session.execute(text(sql), params).first()
        if row and row[0]:
            return str(row[0])
        return None

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
                {_WHERE_LIFECYCLE_ID}
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
            {_WHERE_LIFECYCLE_ID}
        """
        result = self._session.execute(text(sql), params)
        return result.rowcount > 0

    def update_email_thread_id(
        self,
        *,
        lifecycle_id: str,
        email_thread_id: str,
    ) -> bool:
        """No-op: ``email_thread_id`` column removed; thread lives on ``communications``."""
        _ = (lifecycle_id, email_thread_id)
        return True

    def update_shipment_id(
        self,
        *,
        lifecycle_id: str,
        shipment_id: str,
    ) -> bool:
        """Set ``shipment_id`` FK only when currently NULL (idempotent)."""
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET shipment_id = CAST(:shipment_id AS uuid), updated_at = NOW()
                WHERE id = CAST(:lifecycle_id AS uuid)
                  AND shipment_id IS NULL
                """
            ),
            {"shipment_id": shipment_id, "lifecycle_id": lifecycle_id},
        )
        return result.rowcount > 0

    def _find_existing_lifecycle_id_shipment_first(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        """ratecon / pod_lifecycle: ``shipment_id`` FK (UUID) only."""
        if not shipment_id:
            return None
        return self._fetch_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            extra_predicate="AND shipment_id = CAST(:shipment_id AS uuid)",
            extra_params={"shipment_id": shipment_id},
        )

    def find_existing_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        """
        Resolve lifecycle PK by correlation keys.

        ratecon / pod_lifecycle: ``shipment_id`` FK only.
        Other workflows (e.g. load_tendering): ``tender_id`` → ``shipment_id``.
        """
        if workflow_name in ("ratecon", "pod_lifecycle"):
            return self._find_existing_lifecycle_id_shipment_first(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                thread_id=thread_id,
                shipment_id=shipment_id,
            )

        if tender_id:
            found = self._fetch_lifecycle_id(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                extra_predicate="AND tender_id = CAST(:tender_id AS uuid)",
                extra_params={"tender_id": tender_id},
            )
            if found:
                return found

        if shipment_id:
            found = self._fetch_lifecycle_id(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                extra_predicate="AND shipment_id = CAST(:shipment_id AS uuid)",
                extra_params={"shipment_id": shipment_id},
            )
            if found:
                return found
        return None

    def insert_lifecycle(
        self,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
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
                    tender_id,
                    shipment_id
                ) VALUES (
                    CAST(:lifecycle_id AS uuid),
                    CAST(:tenant_id AS uuid),
                    :workflow_name,
                    CAST(:tender_id AS uuid),
                    CAST(:shipment_id AS uuid)
                )
                """
            ),
            {
                "lifecycle_id": lifecycle_id,
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "tender_id": tender_id,
                "shipment_id": shipment_id,
            },
        )

    def _row_dict_from_select(self, row: Any) -> dict[str, Any]:
        return {
            "id": row[0],
            "tenant_id": row[1],
            "workflow_name": row[2],
            "status": row[3],
            "sub_status": row[4],
            "tender_id": row[5] or "",
        }

    def read_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return lifecycle row fields for a PK."""
        row = self._session.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, workflow_name, status::text, sub_status::text,
                       tender_id::text
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return self._row_dict_from_select(row)

    def read_row_by_tender_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest lifecycle row for tenant/workflow/tender correlation."""
        row = self._session.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, workflow_name, status::text, sub_status::text,
                       tender_id::text
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_WORKFLOW}
                  AND tender_id = CAST(:tender_id AS uuid)
                {_LOOKUP_ORDER_LIMIT}
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "tender_id": tender_id,
            },
        ).first()
        if not row:
            return None
        return self._row_dict_from_select(row)

    def read_correlation_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Shipment/thread/tender fields for ``read_lifecycle`` responses."""
        row = self._session.execute(
            text(
                f"""
                SELECT shipment_id::text, workflow_name, tender_id::text
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return {
            "shipment_id": row[0] or "",
            "workflow_name": row[1] or "",
            "tender_id": row[2] or "",
        }

    def find_existing_lifecycle_id_tx(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        return self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )

    def resolve_or_create(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> tuple[str, bool]:
        """Return ``(lifecycle_id, existed)`` without committing."""
        existing_id = self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
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

    def update_shipment_id_tx(
        self,
        *,
        lifecycle_id: str,
        shipment_id: str,
    ) -> bool:
        return self.update_shipment_id(
            lifecycle_id=lifecycle_id,
            shipment_id=shipment_id,
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
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {
                "sub_status": new_sub_status.value,
                "lifecycle_id": lifecycle_id,
            },
        )
        return result.rowcount > 0
