"""Read/write ``communications`` (channel message log)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import execute_scalar, fetchall_dicts, jsonb_param
from app.models.workflow_run_event_type import WorkflowRunEventType

_LIFECYCLE_ON_COMMS = """
(
  c.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
  OR (
    c.workflow_lifecycle_id IS NULL
    AND wr.workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
  )
)
"""


def _carrier_anchors_ranked_sql(*, table_name: str) -> str:
    """CTE: distinct carrier threads per lifecycle ordered by first anchor time."""
    return f"""
    WITH thread_anchors AS (
        SELECT DISTINCT ON (c.thread_id)
               c.thread_id,
               c.created_at AS anchored_at
        FROM {table_name} c
        JOIN workflow_runs wr ON wr.id = c.workflow_run_id
        WHERE c.tenant_id = CAST(:tenant_id AS uuid)
          AND {_LIFECYCLE_ON_COMMS}
          AND wr.event_type = :anchor_event_type
          AND c.thread_id IS NOT NULL
          AND TRIM(c.thread_id) <> ''
        ORDER BY c.thread_id, c.created_at ASC
    ),
    ranked AS (
        SELECT thread_id,
               ROW_NUMBER() OVER (ORDER BY anchored_at ASC)::int AS anchor_attempt
        FROM thread_anchors
    )
    """


class CommunicationsRepository:
    TABLE_NAME = "communications"

    def __init__(self, session: Session) -> None:
        self._session = session

    def list_email_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Return email communications for a thread, oldest first."""
        rows = fetchall_dicts(
            self._session,
            f"""
            SELECT
                id::text AS id,
                direction::text AS direction,
                content,
                metadata,
                created_at
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND thread_id = :thread_id
              AND channel = 'email'::communication_channel
            ORDER BY created_at ASC
            LIMIT :limit
            """,
            {"tenant_id": tenant_id, "thread_id": thread_id, "limit": limit},
            json_keys=frozenset({"metadata"}),
        )

        out: list[dict[str, Any]] = []
        for row in rows:
            meta = row.get("metadata")
            if meta is None:
                meta = {}
            elif not isinstance(meta, dict):
                meta = dict(meta)
            out.append(
                {
                    "id": row["id"],
                    "direction": row["direction"],
                    "content": row["content"],
                    "metadata": meta,
                    "created_at": row["created_at"],
                }
            )
        return out

    def find_active_lifecycle_id_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_name: str = "driver_assignment",
    ) -> str | None:
        """Latest non-terminal lifecycle on a thread (newest ``workflow_lifecycles.updated_at``)."""
        lifecycle_id = execute_scalar(
            self._session,
            f"""
            SELECT wl.id::text
            FROM {self.TABLE_NAME} c
            JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.thread_id = :thread_id
              AND c.workflow_run_id IS NOT NULL
              AND wl.workflow_name = :workflow_name
              AND wl.sub_status::text NOT IN (
                  'uploaded_to_tms', 'cancelled'
              )
            ORDER BY wl.updated_at DESC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_name": workflow_name,
            },
        )
        if not lifecycle_id:
            return None
        return str(lifecycle_id).strip() or None

    def insert(self, row: dict[str, Any]) -> str | None:
        """
        Insert one communication row; return ``communications.id``.

        When ``external_id`` is set, duplicate ``(tenant_id, external_id)`` rows are
        skipped (``ON CONFLICT DO NOTHING``) and this returns ``None``.
        """
        row_id = execute_scalar(
            self._session,
            f"""
            INSERT INTO {self.TABLE_NAME} (
                tenant_id,
                channel,
                direction,
                external_id,
                thread_id,
                content,
                metadata,
                workflow_run_id
            )
            VALUES (
                CAST(:tenant_id AS uuid),
                CAST(:channel AS communication_channel),
                CAST(:direction AS communication_direction),
                :external_id,
                :thread_id,
                :content,
                CAST(:metadata AS jsonb),
                CAST(:workflow_run_id AS uuid)
            )
            ON CONFLICT (tenant_id, external_id)
            WHERE external_id IS NOT NULL
            DO NOTHING
            RETURNING id::text
            """,
            {
                "tenant_id": row["tenant_id"],
                "channel": row["channel"],
                "direction": row["direction"],
                "external_id": row.get("external_id"),
                "thread_id": row.get("thread_id"),
                "content": row.get("content"),
                "metadata": jsonb_param(row.get("metadata") or {}),
                "workflow_run_id": row.get("workflow_run_id"),
            },
        )
        if not row_id:
            return None
        return str(row_id)

    def find_outbound_id_by_idempotency_key(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        channel: str | None = None,
    ) -> str | None:
        """Return outbound communications id matching stored alert idempotency metadata."""
        channel_filter = ""
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "idempotency_key": idempotency_key,
        }
        if channel:
            channel_filter = "AND channel = CAST(:channel AS communication_channel)"
            params["channel"] = channel

        row_id = execute_scalar(
            self._session,
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND direction = 'outbound'::communication_direction
              AND metadata->>'idempotency_key' = :idempotency_key
              {channel_filter}
            LIMIT 1
            """,
            params,
        )
        return str(row_id) if row_id else None

    def find_id_by_tenant_and_external_id(
        self,
        *,
        tenant_id: str,
        external_id: str,
    ) -> str | None:
        """Return ``communications.id`` for a tenant-scoped Unipile ``email_id``."""
        row_id = execute_scalar(
            self._session,
            f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            WHERE tenant_id = CAST(:tenant_id AS uuid)
              AND external_id = :external_id
            LIMIT 1
            """,
            {"tenant_id": tenant_id, "external_id": external_id},
        )
        return str(row_id) if row_id else None

    def link_workflow_run(
        self,
        *,
        communication_id: str,
        workflow_run_id: str,
        workflow_lifecycle_id: str | None = None,
    ) -> bool:
        """Set ``workflow_run_id`` on comm when unlinked or already same run (idempotent)."""
        existing = execute_scalar(
            self._session,
            f"""
            SELECT workflow_run_id::text
            FROM {self.TABLE_NAME}
            WHERE id = CAST(:communication_id AS uuid)
            """,
            {"communication_id": communication_id},
        )
        if existing and str(existing).strip() == str(workflow_run_id).strip():
            if workflow_lifecycle_id:
                self._session.execute(
                    text(
                        f"""
                        UPDATE {self.TABLE_NAME}
                        SET workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)
                        WHERE id = CAST(:communication_id AS uuid)
                          AND workflow_lifecycle_id IS NULL
                        """
                    ),
                    {
                        "communication_id": communication_id,
                        "workflow_lifecycle_id": workflow_lifecycle_id,
                    },
                )
            return True
        lifecycle_set = ""
        params: dict[str, Any] = {
            "communication_id": communication_id,
            "workflow_run_id": workflow_run_id,
        }
        if workflow_lifecycle_id:
            lifecycle_set = (
                ", workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)"
            )
            params["workflow_lifecycle_id"] = workflow_lifecycle_id
        rowcount = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET workflow_run_id = CAST(:workflow_run_id AS uuid)
                    {lifecycle_set}
                WHERE id = CAST(:communication_id AS uuid)
                  AND workflow_run_id IS NULL
                """
            ),
            params,
        ).rowcount
        return rowcount > 0

    def link_workflow_run_to_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_run_id: str,
        workflow_lifecycle_id: str | None = None,
    ) -> int:
        """Patch ``workflow_run_id`` on all unlinked comms for a tenant thread."""
        lifecycle_set = ""
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "workflow_run_id": workflow_run_id,
        }
        if workflow_lifecycle_id:
            lifecycle_set = (
                ", workflow_lifecycle_id = CAST(:workflow_lifecycle_id AS uuid)"
            )
            params["workflow_lifecycle_id"] = workflow_lifecycle_id
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET workflow_run_id = CAST(:workflow_run_id AS uuid)
                    {lifecycle_set}
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND thread_id = :thread_id
                  AND workflow_run_id IS NULL
                """
            ),
            params,
        )
        return int(result.rowcount or 0)

    def find_inbound_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.EMAIL_RECEIVED,
        routing_guide_attempt: int | None = None,
    ) -> str | None:
        """Carrier thread for lifecycle; FTL uses anchor ordinal, LTL uses latest anchor."""
        cte = _carrier_anchors_ranked_sql(table_name=self.TABLE_NAME)
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workflow_lifecycle_id": workflow_lifecycle_id,
            "anchor_event_type": anchor_event_type,
        }
        if routing_guide_attempt is not None:
            params["routing_guide_attempt"] = int(routing_guide_attempt)
            sql = (
                cte
                + """
            SELECT thread_id
            FROM ranked
            WHERE anchor_attempt = :routing_guide_attempt
            LIMIT 1
            """
            )
        else:
            sql = (
                cte
                + """
            SELECT thread_id
            FROM thread_anchors
            ORDER BY anchored_at DESC
            LIMIT 1
            """
            )
        thread_id = execute_scalar(self._session, sql, params)
        if not thread_id:
            return None
        return str(thread_id).strip() or None

    def resolve_lifecycle_id_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_name: str = "load_tendering",
    ) -> str | None:
        """Earliest patched comm on thread → lifecycle (ack ingress)."""
        lifecycle_id = execute_scalar(
            self._session,
            """
            SELECT COALESCE(c.workflow_lifecycle_id, wr.workflow_lifecycle_id)::text
            FROM communications c
            LEFT JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            LEFT JOIN workflow_lifecycles wl ON wl.id = COALESCE(
                c.workflow_lifecycle_id, wr.workflow_lifecycle_id
            )
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.thread_id = :thread_id
              AND (
                c.workflow_lifecycle_id IS NOT NULL
                OR c.workflow_run_id IS NOT NULL
              )
              AND wl.workflow_name = :workflow_name
            ORDER BY c.created_at ASC
            LIMIT 1
            """,
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_name": workflow_name,
            },
        )
        if not lifecycle_id:
            return None
        return str(lifecycle_id).strip() or None

    def find_shipment_context_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """
        Lifecycles on this thread that have a linked ``shipments`` row, newest first.

        Each row: ``lifecycle_id``, ``workflow_name``, ``shipments_row_id``,
        ``shipment_number``, ``updated_at``.
        """
        return fetchall_dicts(
            self._session,
            """
            SELECT wl.id::text AS lifecycle_id,
                   wl.workflow_name,
                   wl.shipment_id::text AS shipments_row_id,
                   s.shipment_number,
                   wl.updated_at
            FROM communications c
            JOIN workflow_runs wr ON wr.id = c.workflow_run_id
            JOIN workflow_lifecycles wl ON wl.id = wr.workflow_lifecycle_id
            JOIN shipments s ON s.id = wl.shipment_id
            WHERE c.tenant_id = CAST(:tenant_id AS uuid)
              AND c.thread_id = :thread_id
              AND c.workflow_run_id IS NOT NULL
              AND wl.shipment_id IS NOT NULL
            ORDER BY wl.updated_at DESC
            """,
            {"tenant_id": tenant_id, "thread_id": thread_id},
        )

    def is_thread_linked_to_lifecycle(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
        routing_guide_attempt: int | None = None,
    ) -> bool:
        """True when this thread is a carrier anchor on the lifecycle (optional attempt ordinal)."""
        cte = _carrier_anchors_ranked_sql(table_name=self.TABLE_NAME)
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "thread_id": thread_id,
            "workflow_lifecycle_id": workflow_lifecycle_id,
            "anchor_event_type": anchor_event_type,
        }
        if routing_guide_attempt is not None:
            params["routing_guide_attempt"] = int(routing_guide_attempt)
            sql = (
                cte
                + """
            SELECT EXISTS (
                SELECT 1
                FROM ranked
                WHERE thread_id = :thread_id
                  AND anchor_attempt = :routing_guide_attempt
            )
            """
            )
        else:
            sql = (
                cte
                + """
            SELECT EXISTS (
                SELECT 1
                FROM thread_anchors
                WHERE thread_id = :thread_id
            )
            """
            )
        linked = execute_scalar(self._session, sql, params)
        return bool(linked)

    def find_linked_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
        routing_guide_attempt: int | None = None,
    ) -> str | None:
        """Carrier thread already anchored for lifecycle (ordinal when attempt is set)."""
        cte = _carrier_anchors_ranked_sql(table_name=self.TABLE_NAME)
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "workflow_lifecycle_id": workflow_lifecycle_id,
            "anchor_event_type": anchor_event_type,
        }
        if routing_guide_attempt is not None:
            params["routing_guide_attempt"] = int(routing_guide_attempt)
            sql = (
                cte
                + """
            SELECT thread_id
            FROM ranked
            WHERE anchor_attempt = :routing_guide_attempt
            LIMIT 1
            """
            )
        else:
            sql = (
                cte
                + """
            SELECT thread_id
            FROM thread_anchors
            ORDER BY anchored_at ASC
            LIMIT 1
            """
            )
        thread_id = execute_scalar(self._session, sql, params)
        if not thread_id:
            return None
        return str(thread_id).strip() or None

    def patch_communication_metadata(
        self,
        *,
        communication_id: str,
        metadata_patch: dict[str, Any],
    ) -> bool:
        """Merge ``metadata_patch`` into ``communications.metadata``."""
        comm_id = str(communication_id or "").strip()
        if not comm_id or not metadata_patch:
            return False
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = COALESCE(metadata, '{{}}'::jsonb) || CAST(:metadata_patch AS jsonb)
                WHERE id = CAST(:communication_id AS uuid)
                """
            ),
            {
                "communication_id": comm_id,
                "metadata_patch": jsonb_param(metadata_patch),
            },
        )
        return int(result.rowcount or 0) > 0

    def thread_attempt_for_lifecycle(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
    ) -> int | None:
        """Ordinal routing-guide attempt for a carrier thread (first anchor = 1)."""
        cte = _carrier_anchors_ranked_sql(table_name=self.TABLE_NAME)
        raw = execute_scalar(
            self._session,
            cte
            + """
            SELECT anchor_attempt
            FROM ranked
            WHERE thread_id = :thread_id
            """,
            {
                "tenant_id": tenant_id,
                "thread_id": thread_id,
                "workflow_lifecycle_id": workflow_lifecycle_id,
                "anchor_event_type": anchor_event_type,
            },
        )
        if raw is None:
            return None
        try:
            attempt = int(raw)
        except (TypeError, ValueError):
            return None
        return attempt if attempt >= 1 else None

    def is_communication_linked_to_run(self, *, communication_id: str) -> bool:
        """True when inbound comm already has a ``workflow_run_id`` (Celery retry guard)."""
        comm_id = str(communication_id or "").strip()
        if not comm_id:
            return False
        linked = execute_scalar(
            self._session,
            f"""
            SELECT EXISTS (
                SELECT 1
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:communication_id AS uuid)
                  AND workflow_run_id IS NOT NULL
            )
            """,
            {"communication_id": comm_id},
        )
        return bool(linked)
