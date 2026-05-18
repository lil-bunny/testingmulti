"""Unipile webhook queues one ``load_tendering`` LangGraph run per projected tender row."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.workflow_classifier_service import WorkflowClassifierService


def _load_tender_payload() -> dict:
    return {
        "webhook_name": "gelita",
        "account_id": "acc-1",
        "email_id": "mail-1",
        "has_attachments": True,
        "attachments": [
            {
                "id": "att-1",
                "name": "loads.xlsx",
                "extension": "xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
        "thread_id": "thr-xyz",
    }


def _stub_persist_tender_ids(**kwargs: object) -> list[str]:
    rows = kwargs.get("projected_rows") or []
    return [
        f"11111111-1111-4111-8111-{i:012x}"[:36]
        for i in range(len(rows))  # type: ignore[arg-type]
    ]


@pytest.fixture(autouse=True)
def stub_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.persist_tender_rows_from_email_import_projection",
        _stub_persist_tender_ids,
    )


@pytest.fixture
def webhook_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"}


@pytest.fixture
def celery_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []
    mock_task = MagicMock()

    def apply_async(**kwargs: dict) -> MagicMock:
        captured.append(kwargs)
        out = MagicMock()
        out.id = "test-celery-task-id"
        return out

    mock_task.apply_async = apply_async
    monkeypatch.setattr("app.api.routes.run_workflow_async", mock_task)
    return captured


@pytest.fixture
def tenant_resolution_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.resolve_email_data_import_tenant_id",
        lambda payload, **_k: "aadc75f4-3f79-45d7-84c3-aa778e226e93",
    )


@pytest.fixture(autouse=True)
def no_db_workflow_graph_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid Postgres when resolver reads tenants.slug."""
    monkeypatch.setattr(
        "app.repositories.tenants_db_repository.get_slug_for_tenant_uuid",
        lambda _tid: None,
    )


@pytest.mark.usefixtures("tenant_resolution_stub")
def test_load_tendering_enqueue_one_row_sets_source_thread_not_thread_id(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "load_tendering"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="cccccccc-cccc-cccc-cccc-cccccccccccc"),
    )
    monkeypatch.setattr(
        "app.api.routes.load_email_data_import_projection",
        lambda **kw: [
            {"order_number": "ORD-1", "customer_match": "c", "product_name": "p", "order_quantity": 1},
        ],
    )

    client = TestClient(create_app())
    r = client.post(
        "/api/webhook/unipile",
        json=_load_tender_payload(),
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("data_import_id") == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert body["execution_ids"] and len(body["execution_ids"]) == 1

    assert len(celery_capture) == 1
    ck = celery_capture[0]["kwargs"]
    assert ck["tenant_id"] == "gelita"
    wp = ck["payload"]
    assert wp["workflow_name"] == "load_tendering"
    assert wp["event_type"] == "email_received"
    assert wp["data_import_id"] == "cccccccc-cccc-cccc-cccc-cccccccccccc"
    assert wp["source_email_thread_id"] == "thr-xyz"
    assert "thread_id" not in wp
    assert wp["tender_row_index"] == 0
    assert wp["tender_row"]["order_number"] == "ORD-1"
    assert wp["load_id"] == "cccccccc-cccc-cccc-cccc-cccccccccccc:0:ORD-1"
    assert wp["tender_id"] == "11111111-1111-4111-8111-000000000000"
    assert wp["execution_id"] == body["execution_ids"][0]
    assert "array_of_tenders" not in wp


@pytest.mark.usefixtures("tenant_resolution_stub")
def test_load_tendering_enqueue_multiple_rows_multiple_tasks(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "load_tendering"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )
    monkeypatch.setattr(
        "app.api.routes.load_email_data_import_projection",
        lambda **kw: [
            {"order_number": "A", "customer_match": "c", "product_name": "p", "order_quantity": 1},
            {"order_number": "B", "customer_match": "c", "product_name": "p", "order_quantity": 2},
        ],
    )

    client = TestClient(create_app())
    r = client.post("/api/webhook/unipile", json=_load_tender_payload(), headers=webhook_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["execution_ids"]) == 2
    assert len(celery_capture) == 2

    wp0 = celery_capture[0]["kwargs"]["payload"]
    wp1 = celery_capture[1]["kwargs"]["payload"]
    assert wp0["tender_row_index"] == 0
    assert wp1["tender_row_index"] == 1
    assert wp0["execution_id"] == body["execution_ids"][0]
    assert wp1["execution_id"] == body["execution_ids"][1]
    assert wp0["load_id"] != wp1["load_id"]
    assert wp0["tender_id"] == "11111111-1111-4111-8111-000000000000"
    assert wp1["tender_id"] == "11111111-1111-4111-8111-000000000001"


@pytest.mark.usefixtures("tenant_resolution_stub")
def test_load_tendering_zero_rows_no_tasks(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "load_tendering"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"),
    )
    monkeypatch.setattr(
        "app.api.routes.load_email_data_import_projection",
        lambda **kw: [],
    )

    client = TestClient(create_app())
    r = client.post("/api/webhook/unipile", json=_load_tender_payload(), headers=webhook_headers)
    assert r.status_code == 200, r.text
    assert r.json() == {
        "message": "success",
        "execution_ids": [],
        "data_import_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
    }
    assert celery_capture == []


@pytest.mark.usefixtures("tenant_resolution_stub")
def test_load_tendering_enqueue_respects_tenant_slug_when_webhook_not_config_key(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    monkeypatch.setattr(
        "app.repositories.tenants_db_repository.get_slug_for_tenant_uuid",
        lambda _tid: "gelita",
    )
    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "load_tendering"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="dddddddd-dddd-dddd-dddd-dddddddddddd"),
    )
    monkeypatch.setattr(
        "app.api.routes.load_email_data_import_projection",
        lambda **kw: [
            {"order_number": "X", "customer_match": "c", "product_name": "p", "order_quantity": 1},
        ],
    )

    p = _load_tender_payload()
    p["webhook_name"] = "not_a_tenant_configs_overlay_key"

    client = TestClient(create_app())
    r = client.post("/api/webhook/unipile", json=p, headers=webhook_headers)
    assert r.status_code == 200, r.text
    assert celery_capture and celery_capture[0]["kwargs"]["tenant_id"] == "gelita"
