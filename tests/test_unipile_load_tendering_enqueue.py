"""Gelita xlsx webhook accepts fast via sync Ingress path (no Celery hop)."""

from __future__ import annotations

from unittest.mock import AsyncMock

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
def ingress_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    async def _accept(**kwargs: object) -> tuple[str, str]:
        captured.append(dict(kwargs))  # type: ignore[arg-type]
        return "mail-1", "accepted"

    monkeypatch.setattr(
        "app.api.v1.webhooks.accept_inbound_unipile_email",
        AsyncMock(side_effect=_accept),
    )
    return captured


@pytest.fixture
def gelita_tenant_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.v1.webhooks.resolve_unipile_tenant",
        lambda payload: UnipileTenantContext(
            tenant_uuid="aadc75f4-3f79-45d7-84c3-aa778e226e93",
            tenant_slug="gelita",
        ),
    )


@pytest.mark.usefixtures("gelita_tenant_stub", "ingress_capture")
def test_gelita_xlsx_webhook_returns_accepted_and_queues_ingress(
    webhook_headers: dict[str, str],
    ingress_capture: list[dict],
) -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/webhook/email",
        json=_load_tender_payload(),
        headers=webhook_headers,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["email_id"] == "mail-1"
    assert body["status"] == "accepted"
    assert len(ingress_capture) == 1
    assert ingress_capture[0]["tenant_slug"] == "gelita"
    assert ingress_capture[0]["payload"]["email_id"] == "mail-1"
