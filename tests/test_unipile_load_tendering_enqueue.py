"""Gelita xlsx webhook accepts fast and queues background ingest."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.unipile_tenant_resolution import UnipileTenantContext


def _load_tender_payload() -> dict:
    return {
        "webhook_name": "gelita",
        "account_id": "acc-1",
        "email_id": "mail-1",
        "has_attachments": True,
        "attachments": [
            {
                "id": "att-1",
                "name": "customers_orders_loads.xlsx",
                "extension": "xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
        "thread_id": "thr-xyz",
    }


@pytest.fixture
def webhook_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"}


@pytest.fixture
def ingest_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    def _enqueue(**kwargs: object) -> tuple[str, str]:
        captured.append(dict(kwargs))  # type: ignore[arg-type]
        return "test-ingest-task-id", "queued"

    monkeypatch.setattr(
        "app.services.gelita_inbound_email_service.enqueue_load_tendering_tender_created_ingest",
        _enqueue,
    )
    return captured


@pytest.fixture
def gelita_tenant_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.resolve_unipile_tenant",
        lambda payload: UnipileTenantContext(
            tenant_uuid="aadc75f4-3f79-45d7-84c3-aa778e226e93",
            tenant_slug="gelita",
        ),
    )


@pytest.fixture(autouse=True)
def no_db_workflow_graph_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.repositories.tenants_db_repository.get_slug_for_tenant_uuid",
        lambda _tid: "gelita",
    )


@pytest.mark.usefixtures("gelita_tenant_stub", "ingest_capture")
def test_gelita_xlsx_webhook_returns_accepted_and_queues_ingest(
    webhook_headers: dict[str, str],
    ingest_capture: list[dict],
) -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/webhook/email",
        json=_load_tender_payload(),
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["message"] == "accepted"
    assert body["event_type"] == "tender_created"
    assert body["task_id"] == "test-ingest-task-id"
    assert body["status"] == "queued"
    assert len(ingest_capture) == 1
    assert ingest_capture[0]["tenant_slug"] == "gelita"
    assert ingest_capture[0]["payload"]["email_id"] == "mail-1"
