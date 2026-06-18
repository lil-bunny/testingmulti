"""Insert rows into ``activity_logs`` (workflow audit trail)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import execute_scalar, jsonb_param


class ActivityLogsRepository:
    TABLE_NAME = "activity_logs"

    def __init__(self, session: Session) -> None:
        self._session = session

    def insert(self, row: dict[str, Any]) -> str:
        """Insert one activity row; return ``activity_logs.id``."""
        row_id = execute_scalar(
            self._session,
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
                metadata,
                communication_id
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:workflow_lifecycle_id AS uuid),
                CAST(:workflow_run_id AS uuid),
                CAST(:activity_type AS activity_log_type),
                :description,
                CAST(:from_status AS lifecycle_status),
                CAST(:to_status AS lifecycle_status),
                CAST(:from_sub_status AS lifecycle_sub_status),
                CAST(:to_sub_status AS lifecycle_sub_status),
                :actor_type,
                CAST(:actor_id AS uuid),
                CAST(:metadata AS jsonb),
                CAST(:communication_id AS uuid)
            )
            RETURNING id::text
            """,
            {
                "tenant_id": row["tenant_id"],
                "workflow_lifecycle_id": row.get("workflow_lifecycle_id"),
                "workflow_run_id": row.get("workflow_run_id"),
                "activity_type": row["activity_type"],
                "description": row.get("description"),
                "from_status": row.get("from_status"),
                "to_status": row.get("to_status"),
                "from_sub_status": row.get("from_sub_status"),
                "to_sub_status": row.get("to_sub_status"),
                "actor_type": row.get("actor_type"),
                "actor_id": row.get("actor_id"),
                "metadata": jsonb_param(row.get("metadata") or {}),
                "communication_id": row.get("communication_id"),
            },
        )
        if not row_id:
            raise RuntimeError("activity_logs insert returned no id")
        return str(row_id)

    def link_communication(
        self,
        *,
        activity_log_id: str,
        tenant_id: str,
        communication_id: str,
        metadata_patch: dict[str, Any] | None = None,
    ) -> bool:
        """Set ``communication_id`` and merge ``metadata`` when not yet linked."""
        rowcount = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET communication_id = CAST(:communication_id AS uuid),
                    metadata = metadata || CAST(:metadata_patch AS jsonb)
                WHERE id = CAST(:activity_log_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                  AND communication_id IS NULL
                """
            ),
            {
                "activity_log_id": activity_log_id,
                "tenant_id": tenant_id,
                "communication_id": communication_id,
                "metadata_patch": jsonb_param(metadata_patch or {}),
            },
        ).rowcount
        return rowcount > 0
