"""Append-only writes to ``activity_logs`` (psycopg; matches ``WorkflowLifecycleService`` style)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import psycopg

from app.core.config import settings
from app.models.status import StatusSubType
from app.models.status import StatusType
from app.models.actor_type import ActorType

class ActivityLogService:
    TABLE_NAME = "activity_logs"

    def _conn(self):
        return psycopg.connect(settings.DATABASE_URL)

    @staticmethod
    def _status_value(
        value: StatusType | StatusSubType | str | None,
    ) -> str | None:
        if value is None:
            return None
        if isinstance(value, (StatusType, StatusSubType)):
            return value.value
        s = str(value).strip()
        return s or None

    @staticmethod
    def _clean_uuid(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        try:
            uuid.UUID(s)
        except ValueError:
            return None
        return s

    def insert(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str | None = None,
        workflow_run_id: str | None = None,
        activity_type: str,
        message: str | None = None,
        from_status: StatusType | None = None,
        to_status: StatusType | None = None,
        from_sub_status: StatusSubType | None = None,
        to_sub_status: StatusSubType | None = None,
        actor_type: ActorType = ActorType.SYSTEM.value,
        actor_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        tid = self._clean_uuid(tenant_id)
        if not tid:
            raise ValueError("tenant_id must be a UUID string")

        wl = self._clean_uuid(workflow_lifecycle_id) if workflow_lifecycle_id else None
        wr = self._clean_uuid(workflow_run_id) if workflow_run_id else None
        aid = self._clean_uuid(actor_id) if actor_id else str(uuid.uuid4())

        payload_json = json.dumps(payload or {})
        

        conn = self._conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {self.TABLE_NAME} (
                        id,
                        tenant_id,
                        workflow_lifecycle_id,
                        workflow_run_id,
                        activity_type,
                        message,
                        from_status,
                        to_status,
                        from_sub_status,
                        to_sub_status,
                        actor_type,
                        actor_id,
                        payload
                    )
                    VALUES (
                        gen_random_uuid(),
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
                        %s::jsonb
                    )
                    """,
                    (
                        tid,
                        wl,
                        wr,
                        activity_type,
                        message,
                        self._status_value(from_status),
                        self._status_value(to_status),
                        self._status_value(from_sub_status),
                        self._status_value(to_sub_status),
                        self._status_value(actor_type) or ActorType.SYSTEM.value,
                        aid,
                        payload_json,
                    ),
                )
            conn.commit()
        finally:
            conn.close()
