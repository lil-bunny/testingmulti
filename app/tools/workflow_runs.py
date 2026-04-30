"""Recorded workflow executions (`workflow_runs`).

`tenant_id` is the Freight tenant key (`WorkflowService.run(..., tenant_id=...)` /
`tenant_id` on workflow state).

Idempotency:
- `workflow_instance_id` + `event_type`, except unlimited `process_pod_followup` rows.
- Duplicate Turvo `route_completed` webhooks per `tenant_id` + `shipment_id` via partial unique.
  (Load-only webhooks are not keyed in this table.)

Reminders persist as synthetic event strings `reminder_1`, `reminder_2`, … derived from scheduler
payload `reminder_step` — not duplicate `event_type` values per instance.

`ensure_table` exists for local dev; Alembic owns the canonical schema.
"""

from __future__ import annotations

import uuid

import psycopg
from psycopg import errors as pg_errors

from app.core.config import settings


TABLE_NAME = "workflow_runs"


def _conn():
    return psycopg.connect(settings.DATABASE_URL)


def ensure_table():
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    workflow_instance_id TEXT NOT NULL,
                    shipment_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{TABLE_NAME}_created_at
                ON {TABLE_NAME}(created_at DESC)
                """
            )
            cur.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE_NAME}_wi_entry_event
                ON {TABLE_NAME}(workflow_instance_id, event_type)
                WHERE event_type <> 'process_pod_followup'
                """
            )
            cur.execute(
                f"""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_{TABLE_NAME}_tenant_shipment_route_completed
                ON {TABLE_NAME}(tenant_id, shipment_id)
                WHERE event_type = 'route_completed' AND shipment_id IS NOT NULL
                """
            )
        conn.commit()
    finally:
        conn.close()


def _none_if_blank(val: str | None) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s if s else None


def reminder_run_event_type(reminder_step: int | None) -> str | None:
    """DB `event_type` for a Celery POD reminder."""
    if reminder_step is None:
        return None
    return f"reminder_{int(reminder_step)}"


def workflow_initial_path_blocked(
    *,
    tenant_id: str | None,
    event_type: str | None,
    workflow_instance_id: str | None,
    shipment_id: str | None,
) -> bool:
    """
    Whether `pod_request_blocked` should be True: a prior recorded run already covers
    this `route_completed` trigger (replay or duplicate Turvo webhook).

    Requires `shipment_id`; load-only route signals are not deduped via this table.
    """
    ensure_table()
    tid = _none_if_blank(tenant_id)
    wi = _none_if_blank(workflow_instance_id)
    et = _none_if_blank(event_type)
    sid = _none_if_blank(shipment_id)

    if not tid or not wi or et != "route_completed" or not sid:
        return False

    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {TABLE_NAME} wr
                    WHERE wr.workflow_instance_id = %s AND wr.event_type = %s
                    UNION ALL
                    SELECT 1 FROM {TABLE_NAME} wr
                    WHERE wr.tenant_id = %s
                      AND wr.event_type = 'route_completed'
                      AND wr.shipment_id IS NOT DISTINCT FROM %s
                )
                """,
                (wi, et, tid, sid),
            )
            row = cur.fetchone()
            return bool(row and row[0])
    finally:
        conn.close()


def record_workflow_run(
    *,
    tenant_id: str | None,
    event_type: str,
    workflow_instance_id: str | None,
    shipment_id: str | None = None,
) -> bool:
    """
    Insert one run row. Returns True when a new row was written; False when a matching
    unique constraint already stored this run / anchor.
    """
    tid = _none_if_blank(tenant_id)
    wi = _none_if_blank(workflow_instance_id)
    et = (event_type or "").strip()

    if not tid or not wi or not et:
        return False

    sid = _none_if_blank(shipment_id)

    run_id = str(uuid.uuid4())
    ensure_table()
    conn = _conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {TABLE_NAME} (
                    id,
                    tenant_id,
                    event_type,
                    workflow_instance_id,
                    shipment_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                (run_id, tid, et, wi, sid),
            )
        conn.commit()
        return True
    except pg_errors.UniqueViolation:
        conn.rollback()
        return False
    finally:
        conn.close()
