from typing import Any, Optional
import uuid

from app.core.config import settings
from app.tools.turvo import load_id_to_shipment_id

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


def _pg_read_by_shipment_id(shipment_id: str) -> dict:
    _ensure_pg_table()
    conn = _try_pg_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT workflow_name, workflow_instance_id, shipment_id, load_id, email_thread_id
                FROM {settings.WORKFLOW_CORRELATION_TABLE}
                WHERE shipment_id = %s
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (shipment_id,),
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


def read_correlation_by_shipment_id(shipment_id: str) -> dict:
    """Return correlation row where ``shipment_id`` column matches (strict; not load/thread columns)."""
    sid = (shipment_id or "").strip()
    if not sid:
        return {"found": False, "payload": {}}
    return _pg_read_by_shipment_id(sid)


def ratecon_shipment_in_workflow_correlation(
    load_id: Optional[str] = None,
    *,
    shipment_id: Optional[str] = None,
    app_user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Resolve Turvo ``shipment_id`` when needed, then look up workflow_correlation by that column only."""

    lid_raw: Optional[str] = None
    if load_id is not None:
        ls = str(load_id).strip()
        if ls:
            lid_raw = ls

    sid: Optional[str] = None
    if shipment_id is not None:
        ss = str(shipment_id).strip()
        if ss:
            sid = ss

    empty_wf = {"found": False, "payload": {}}

    if not sid:
        if not lid_raw:
            return {
                "in_workflow_correlation": False,
                "shipment_id": None,
                "load_id": lid_raw,
                "workflow_correlation": empty_wf,
                "message": "missing_load_id_and_shipment_id",
            }
        turvo = load_id_to_shipment_id(lid_raw, app_user_id=app_user_id)
        if turvo.get("success") and turvo.get("shipment_id"):
            sid = str(turvo["shipment_id"]).strip()
        else:
            return {
                "in_workflow_correlation": False,
                "shipment_id": None,
                "load_id": lid_raw,
                "workflow_correlation": empty_wf,
                "message": turvo.get("message", "could_not_resolve_shipment_id"),
            }

    wf = read_correlation_by_shipment_id(sid)
    return {
        "in_workflow_correlation": bool(wf.get("found")),
        "shipment_id": sid,
        "load_id": lid_raw,
        "workflow_correlation": wf,
    }


def persist_correlation_thread_for_shipment(
    shipment_id: str,
    load_id: str,
    email_thread_id: str,
    *,
    workflow_instance_id: Optional[str] = None,
    workflow_name: Optional[str] = None,
) -> dict[str, Any]:
    """Set ``email_thread_id`` / ``load_id`` on workflow_correlation for ``shipment_id`` (read + upsert).

    If no row exists, supply ``workflow_instance_id`` (and optionally ``workflow_name``) from the
    current workflow run so ``upsert_by_key`` can insert.
    """
    sid = (shipment_id or "").strip()
    tid = (email_thread_id or "").strip()
    if not sid or not tid:
        return {"stored": False, "error": "missing_shipment_id_or_email_thread_id"}

    wf = read_correlation_by_shipment_id(sid)
    if wf.get("found"):
        p = wf.get("payload") or {}
        wid = str(p.get("workflow_instance_id") or "").strip()
        if not wid:
            return {"stored": False, "error": "missing_workflow_instance_id"}

        lid = (load_id or "").strip()
        load_val = lid if lid else str(p.get("load_id") or "").strip()

        payload = {
            "workflow_name": p.get("workflow_name") or "pod_lifecycle",
            "workflow_instance_id": wid,
            "shipment_id": sid,
            "load_id": load_val,
            "email_thread_id": tid,
        }
        result = upsert_by_key(sid, payload)
        return {"stored": True, "workflow_correlation": result}

    wid_new = (workflow_instance_id or "").strip()
    if not wid_new:
        return {"stored": False, "error": "missing_workflow_instance_id_new_row"}

    wfn = ((workflow_name or "").strip() or "ratecon")
    lid = (load_id or "").strip()
    payload = {
        "workflow_name": wfn,
        "workflow_instance_id": wid_new,
        "shipment_id": sid,
        "load_id": lid,
        "email_thread_id": tid,
    }
    result = upsert_by_key(sid, payload)
    return {"stored": True, "workflow_correlation": result}


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
