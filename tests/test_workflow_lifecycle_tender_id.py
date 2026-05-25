"""Unit tests for optional ``tender_id`` on ``WorkflowLifecycleService``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.workflow_lifecycle_service import WorkflowLifecycleService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TENDER_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
EXISTING_LIFECYCLE = "cccccccc-cccc-cccc-cccc-cccccccccccc"


def test_extract_tender_id_accepts_uuid() -> None:
    assert (
        WorkflowLifecycleService._extract_tender_id({"tender_id": TENDER_UUID})
        == TENDER_UUID
    )


def test_extract_tender_id_rejects_non_uuid() -> None:
    assert WorkflowLifecycleService._extract_tender_id({"tender_id": "gelita"}) is None


def test_find_existing_lifecycle_queries_tender_id_first() -> None:
    log: list[tuple[str, tuple]] = []
    svc = WorkflowLifecycleService()
    cur = MagicMock()
    cur.fetchone.return_value = None

    svc._find_existing_lifecycle_id(
        cur,
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        tender_id=TENDER_UUID,
        thread_id="thr-1",
        shipment_id=None,
    )

    assert cur.execute.call_count >= 1
    first_sql = cur.execute.call_args_list[0][0][0]
    first_params = cur.execute.call_args_list[0][0][1]
    assert "tender_id" in first_sql
    assert first_params == (TENANT_UUID, "load_tendering", TENDER_UUID)


def test_resolve_or_create_reuses_lifecycle_by_tender_id() -> None:
    log: list[tuple[str, tuple]] = []

    def fake_conn():
        cur = MagicMock()
        fetch_results = [EXISTING_LIFECYCLE]

        def execute(sql, params=None):
            log.append((sql, params or ()))

        def fetchone():
            if fetch_results:
                return (fetch_results.pop(0),)
            return None

        cur.execute = execute
        cur.fetchone = fetchone
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    svc = WorkflowLifecycleService()
    with patch.object(svc, "_conn", fake_conn):
        with patch(
            "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
            return_value=TENANT_UUID,
        ):
            result = svc.resolve_or_create_lifecycle(
                tenant_id="gelita",
                workflow_name="load_tendering",
                payload={"tender_id": TENDER_UUID},
            )

    assert result.workflow_lifecycle_id == EXISTING_LIFECYCLE
    assert result.existed is True
    assert any("tender_id" in sql for sql, _ in log)


def test_resolve_or_create_without_tender_id_omits_tender_lookup() -> None:
    log: list[tuple[str, tuple]] = []

    def fake_conn():
        cur = MagicMock()

        def execute(sql, params=None):
            log.append((sql, params or ()))

        cur.execute = execute
        cur.fetchone = MagicMock(return_value=None)
        conn = MagicMock()
        conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
        conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
        return conn

    svc = WorkflowLifecycleService()
    with patch.object(svc, "_conn", fake_conn):
        with patch(
            "app.services.workflow_lifecycle_service.resolve_graph_tenant_to_uuid",
            return_value=TENANT_UUID,
        ):
            svc.resolve_or_create_lifecycle(
                tenant_id="t3ra",
                workflow_name="pod_lifecycle",
                payload={"thread_id": "thr-99", "shipment_id": "S1"},
            )

    assert not any("AND tender_id =" in sql for sql, _ in log)
