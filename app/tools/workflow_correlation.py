from typing import Optional
import uuid

from app.core.config import settings

import psycopg


_PG_READY = False


def _try_pg_connection():
    return psycopg.connect(settings.DATABASE_URL)


def _ensure_pg_table():
    global _PG_READY
    if _PG_READY:
        return
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {settings.WORKFLOW_CORRELATION_TABLE} (
                    id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    workflow_instance_id TEXT NOT NULL UNIQUE,
                    shipment_id TEXT,
                    load_id TEXT,
                    email_thread_id TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{settings.WORKFLOW_CORRELATION_TABLE}_shipment_id "
                f"ON {settings.WORKFLOW_CORRELATION_TABLE}(shipment_id)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{settings.WORKFLOW_CORRELATION_TABLE}_load_id "
                f"ON {settings.WORKFLOW_CORRELATION_TABLE}(load_id)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS idx_{settings.WORKFLOW_CORRELATION_TABLE}_email_thread_id "
                f"ON {settings.WORKFLOW_CORRELATION_TABLE}(email_thread_id)"
            )
        conn.commit()
        _PG_READY = True
    finally:
        conn.close()


def _pg_read_by_key(key: str) -> Optional[dict]:
    _ensure_pg_table()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT workflow_name, workflow_instance_id, shipment_id, load_id, email_thread_id
                FROM {settings.WORKFLOW_CORRELATION_TABLE}
                WHERE email_thread_id = %s
                   OR load_id = %s
                   OR shipment_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (key, key, key),
            )
            row = cur.fetchone()
            if not row:
                return {"found": False, "payload": {}}
            return {
                "found": True,
                "payload": {
                    "workflow_name": row[0] or "",
                    "workflow_instance_id": row[1] or "",
                    "shipment_id": row[2] or "",
                    "load_id": row[3] or "",
                    "email_thread_id": row[4] or "",
                },
            }
    finally:
        conn.close()


def _pg_upsert_by_key(key: str, payload: dict) -> Optional[dict]:
    _ensure_pg_table()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {settings.WORKFLOW_CORRELATION_TABLE}
                    (id, workflow_name, workflow_instance_id, shipment_id, load_id, email_thread_id)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (workflow_instance_id) DO UPDATE
                SET workflow_name = COALESCE(EXCLUDED.workflow_name, {settings.WORKFLOW_CORRELATION_TABLE}.workflow_name),
                    shipment_id = COALESCE(EXCLUDED.shipment_id, {settings.WORKFLOW_CORRELATION_TABLE}.shipment_id),
                    load_id = COALESCE(EXCLUDED.load_id, {settings.WORKFLOW_CORRELATION_TABLE}.load_id),
                    email_thread_id = COALESCE(EXCLUDED.email_thread_id, {settings.WORKFLOW_CORRELATION_TABLE}.email_thread_id),
                    updated_at = NOW()
                RETURNING workflow_name, workflow_instance_id, shipment_id, load_id, email_thread_id
                """,
                (
                    str(uuid.uuid4()),
                    payload.get("workflow_name", "pod_lifecycle"),
                    payload.get("workflow_instance_id", ""),
                    payload.get("shipment_id") or (key if payload.get("shipment_id") is not None else None),
                    payload.get("load_id") or (key if payload.get("load_id") is not None else None),
                    payload.get("email_thread_id") or payload.get("thread_id"),
                ),
            )
            merged = cur.fetchone()
        conn.commit()
        return {
            "key": key,
            "payload": {
                "workflow_name": merged[0] if merged else "",
                "workflow_instance_id": merged[1] if merged else "",
                "shipment_id": merged[2] if merged else "",
                "load_id": merged[3] if merged else "",
                "email_thread_id": merged[4] if merged else "",
            },
        }
    finally:
        conn.close()


def _pg_map_thread_to_workflow(thread_id: str, workflow_instance_id: str) -> bool:
    _ensure_pg_table()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {settings.WORKFLOW_CORRELATION_TABLE}
                    (id, workflow_name, workflow_instance_id, email_thread_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (workflow_instance_id) DO UPDATE
                SET email_thread_id = EXCLUDED.email_thread_id,
                    updated_at = NOW()
                """,
                (str(uuid.uuid4()), "pod_lifecycle", workflow_instance_id, thread_id),
            )
        conn.commit()
        return True
    finally:
        conn.close()


def _pg_get_workflow_for_thread(thread_id: str) -> Optional[str]:
    _ensure_pg_table()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT workflow_instance_id
                FROM {settings.WORKFLOW_CORRELATION_TABLE}
                WHERE email_thread_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (thread_id,),
            )
            row = cur.fetchone()
            return row[0] if row else ""
    finally:
        conn.close()


def read_by_key(key: str) -> dict:
    pg_result = _pg_read_by_key(key)
    if pg_result is None:
        return {"found": False, "payload": {}}
    return pg_result


def upsert_by_key(key: str, payload: dict) -> dict:
    pg_result = _pg_upsert_by_key(key, payload)
    if pg_result is None:
        raise RuntimeError("Failed to persist workflow correlation payload in Postgres")
    return pg_result


def map_thread_to_workflow(thread_id: str, workflow_instance_id: str):
    if not thread_id or not workflow_instance_id:
        return
    if not _pg_map_thread_to_workflow(thread_id, workflow_instance_id):
        raise RuntimeError("Failed to map thread to workflow instance in Postgres")


def get_workflow_for_thread(thread_id: str) -> str:
    value = _pg_get_workflow_for_thread(thread_id)
    if value is None:
        return ""
    return value
