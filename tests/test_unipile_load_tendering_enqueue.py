"""Gelita xlsx webhook admits to the Pre-Lifecycle Work Queue (Heavy Ingress Work)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.email_ingress_work_queue_serializer_service import (
    EmailIngressAdmitResult,
)
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


@pytest.fixture
def heavy_ingress_admit_capture(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    captured: list[dict] = []

    class _StubSerializer:
        def admit(self, **kwargs: object) -> EmailIngressAdmitResult:
            captured.append(dict(kwargs))
            return EmailIngressAdmitResult(
                email_id=str(kwargs["email_id"]),
                inbox_key=f"inbox:email_ingress:{kwargs['email_id']}",
                status="started",
                length=1,
                celery_task_id="task-1",
            )

    monkeypatch.setattr(
        "app.api.v1.webhooks.EmailIngressWorkQueueSerializerService",
        MagicMock(return_value=_StubSerializer()),
    )
    return captured


@pytest.mark.usefixtures("gelita_tenant_stub", "ingress_capture")
def test_gelita_xlsx_webhook_queues_heavy_ingress_work_not_inline_ingress(
    webhook_headers: dict[str, str],
    ingress_capture: list[dict],
    heavy_ingress_admit_capture: list[dict],
) -> None:
    """
    Sheet attachments are heavy (Edge Heavy-Work Gate match): admit to the
    Pre-Lifecycle Work Queue, never call the inline Ingress accept path.
    """
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
    assert body["status"] == "queued_for_processing"
    assert len(ingress_capture) == 0

    assert len(heavy_ingress_admit_capture) == 1
    admitted = heavy_ingress_admit_capture[0]
    assert admitted["email_id"] == "mail-1"
    assert admitted["tenant_slug"] == "gelita"
    assert admitted["payload"]["email_id"] == "mail-1"
