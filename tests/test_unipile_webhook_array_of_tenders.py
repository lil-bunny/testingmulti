"""Unipile webhook: ``data_import_id`` and ``array_of_tenders`` attachment to Celery payloads."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.workflow_classifier_service import WorkflowClassifierService


@pytest.fixture(autouse=True)
def noop_tenders_persist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.routes.persist_tender_rows_from_email_import_projection",
        lambda **kwargs: 0,
    )


@pytest.fixture(autouse=True)
def stub_data_import_tenant_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid live DB for tenants.settings ``email_webhook_name`` lookup in route tests."""

    monkeypatch.setattr(
        "app.api.routes.resolve_email_data_import_tenant_id",
        lambda payload, **_k: "aadc75f4-3f79-45d7-84c3-aa778e226e93",
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


def test_unipile_webhook_ratecon_carries_import_id_but_not_array_of_tenders(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    """``array_of_tenders`` must not attach to Celery payloads for ratecon/pod."""

    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "ratecon"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    )

    client = TestClient(create_app())
    r = client.post(
        "/api/webhook/unipile",
        json=RATECON_WEBHOOK_PAYLOAD,
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    assert celery_capture, "Celery apply_async was not called"
    wpayload = celery_capture[0]["kwargs"]["payload"]
    assert wpayload["data_import_id"] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert "array_of_tenders" not in wpayload


def test_unipile_webhook_omits_import_keys_when_no_import_id(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "ratecon"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value=None),
    )

    def load_only_when_no_import_id(**kw):
        assert not kw.get("data_import_id")
        return []

    monkeypatch.setattr(
        "app.api.routes.load_email_data_import_projection",
        load_only_when_no_import_id,
    )

    client = TestClient(create_app())
    r = client.post(
        "/api/webhook/unipile",
        json=RATECON_WEBHOOK_PAYLOAD,
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    wpayload = celery_capture[0]["kwargs"]["payload"]
    assert "data_import_id" not in wpayload
    assert "array_of_tenders" not in wpayload


def test_unipile_webhook_pod_carries_import_id_but_not_array_of_tenders(
    monkeypatch: pytest.MonkeyPatch,
    webhook_headers: dict[str, str],
    celery_capture: list[dict],
) -> None:
    from tests.e2e.fixtures.main import RATECON_WEBHOOK_PAYLOAD

    monkeypatch.setattr(
        WorkflowClassifierService,
        "classify_workflow_type",
        lambda self, payload: {"workflow_name": "pod_lifecycle"},
    )
    monkeypatch.setattr(
        "app.api.routes.process_email_webhook_attachment_import",
        AsyncMock(return_value="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
    )

    client = TestClient(create_app())
    r = client.post(
        "/api/webhook/unipile",
        json=RATECON_WEBHOOK_PAYLOAD,
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    wpayload = celery_capture[0]["kwargs"]["payload"]
    assert wpayload["data_import_id"] == "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    assert "array_of_tenders" not in wpayload
