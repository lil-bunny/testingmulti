"""Feature tests: POST /api/v1/webhook/email L1 routing by inbound_routing_emails."""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.email_ingress_work_queue_serializer_service import (
    EmailIngressAdmitResult,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_GELITA_EMAIL = "routing-test-gelita@freightx.test"
_T3RA_EMAIL = "routing-test-t3ra@freightx.test"
_SHARED_EMAIL = "routing-test-shared@freightx.test"


def _db_available() -> bool:
    url = (settings.DATABASE_URL or "").strip()
    if not url:
        return False
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_name = 'tenants'
                    """
                )
                if cur.fetchone() is None:
                    return False
                cur.execute(
                    """
                    SELECT count(*) FROM tenants WHERE slug IN ('gelita', 't3ra')
                    """
                )
                row = cur.fetchone()
                return row is not None and int(row[0]) >= 2
    except Exception:
        return False


def _fetch_tenant_row(slug: str) -> dict[str, Any] | None:
    url = (settings.DATABASE_URL or "").strip()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, settings
                FROM tenants
                WHERE lower(trim(slug)) = lower(%s)
                ORDER BY id
                LIMIT 1
                """,
                (slug,),
            )
            row = cur.fetchone()
            if not row:
                return None
            settings_raw = row[1]
            if isinstance(settings_raw, dict):
                settings_dict = settings_raw
            else:
                settings_dict = json.loads(settings_raw)
            return {"id": row[0], "settings": settings_dict}


def _merge_inbound_routing_emails(settings_dict: dict[str, Any], emails: list[str]) -> dict[str, Any]:
    merged = dict(settings_dict)
    merged["inbound_routing_emails"] = emails
    return merged


def _update_tenant_settings(tenant_id: str, settings_dict: dict[str, Any]) -> None:
    url = (settings.DATABASE_URL or "").strip()
    with psycopg.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE tenants SET settings = %s::jsonb WHERE id = %s::uuid",
                (json.dumps(settings_dict), tenant_id),
            )
        conn.commit()


def _payload_with_to(*emails: str, **extra: object) -> dict:
    body: dict = {
        "to_attendees": [
            {"identifier": email, "identifier_type": "EMAIL_ADDRESS"} for email in emails
        ],
        "cc_attendees": [],
        "bcc_attendees": [],
        "account_id": "acc-routing-test",
        "email_id": "mail-routing-test",
        "thread_id": "thr-routing-test",
    }
    body.update(extra)
    return body


def _gelita_xlsx_payload(email: str) -> dict:
    return _payload_with_to(
        email,
        has_attachments=True,
        attachments=[
            {
                "id": "att-routing-1",
                "name": "customers_orders_loads.xlsx",
                "extension": "xlsx",
                "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            },
        ],
    )


@pytest.fixture
def webhook_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {settings.UNIPILE_WEBHOOK_SECRET}"}


@pytest.fixture
def seed_inbound_routing_tenants() -> Iterator[dict[str, dict[str, Any]]]:
    gelita_row = _fetch_tenant_row("gelita")
    t3ra_row = _fetch_tenant_row("t3ra")
    assert gelita_row and t3ra_row, "gelita and t3ra tenant rows required"

    snapshot = {
        "gelita": {"id": gelita_row["id"], "settings": dict(gelita_row["settings"])},
        "t3ra": {"id": t3ra_row["id"], "settings": dict(t3ra_row["settings"])},
    }

    _update_tenant_settings(
        gelita_row["id"],
        _merge_inbound_routing_emails(gelita_row["settings"], [_GELITA_EMAIL]),
    )
    _update_tenant_settings(
        t3ra_row["id"],
        _merge_inbound_routing_emails(t3ra_row["settings"], [_T3RA_EMAIL]),
    )

    yield snapshot

    _update_tenant_settings(snapshot["gelita"]["id"], snapshot["gelita"]["settings"])
    _update_tenant_settings(snapshot["t3ra"]["id"], snapshot["t3ra"]["settings"])


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


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or gelita/t3ra tenants missing")
@pytest.mark.usefixtures("seed_inbound_routing_tenants")
def test_webhook_routes_gelita_by_recipient_email(
    webhook_headers: dict[str, str],
    ingress_capture: list[dict],
    heavy_ingress_admit_capture: list[dict],
) -> None:
    """
    Gelita xlsx attachment is heavy (Edge Heavy-Work Gate match): tenant routing
    still resolves via ``inbound_routing_emails``, but Ingress admits to the
    Pre-Lifecycle Work Queue instead of running inline.
    """
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/webhook/email",
        json=_gelita_xlsx_payload(_GELITA_EMAIL),
        headers=webhook_headers,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["status"] == "queued_for_processing"
    assert len(ingress_capture) == 0
    assert len(heavy_ingress_admit_capture) == 1
    assert heavy_ingress_admit_capture[0]["tenant_slug"] == "gelita"


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or gelita/t3ra tenants missing")
@pytest.mark.usefixtures("seed_inbound_routing_tenants")
def test_webhook_routes_t3ra_by_recipient_email(
    webhook_headers: dict[str, str],
    ingress_capture: list[dict],
) -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/webhook/email",
        json=_payload_with_to(_T3RA_EMAIL, subject="hello", has_attachments=False),
        headers=webhook_headers,
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted"] is True
    assert body["status"] == "accepted"
    assert len(ingress_capture) == 1
    assert ingress_capture[0]["tenant_slug"] == "t3ra"


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or gelita/t3ra tenants missing")
@pytest.mark.usefixtures("seed_inbound_routing_tenants")
def test_webhook_invalid_when_unknown_recipient(
    webhook_headers: dict[str, str],
) -> None:
    client = TestClient(create_app())
    r = client.post(
        "/api/v1/webhook/email",
        json=_payload_with_to("unknown-routing@freightx.test"),
        headers=webhook_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"message": "invalid webhook"}


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or gelita/t3ra tenants missing")
def test_webhook_invalid_when_multiple_tenants_match(
    webhook_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    gelita_row = _fetch_tenant_row("gelita")
    t3ra_row = _fetch_tenant_row("t3ra")
    assert gelita_row and t3ra_row

    snapshot = {
        "gelita": {"id": gelita_row["id"], "settings": dict(gelita_row["settings"])},
        "t3ra": {"id": t3ra_row["id"], "settings": dict(t3ra_row["settings"])},
    }
    shared_settings_gelita = _merge_inbound_routing_emails(
        gelita_row["settings"], [_SHARED_EMAIL]
    )
    shared_settings_t3ra = _merge_inbound_routing_emails(t3ra_row["settings"], [_SHARED_EMAIL])

    _update_tenant_settings(gelita_row["id"], shared_settings_gelita)
    _update_tenant_settings(t3ra_row["id"], shared_settings_t3ra)

    try:
        caplog.set_level("WARNING")
        client = TestClient(create_app())
        r = client.post(
            "/api/v1/webhook/email",
            json=_payload_with_to(_SHARED_EMAIL),
            headers=webhook_headers,
        )
        assert r.status_code == 200, r.text
        assert r.json() == {"message": "invalid webhook: multiple tenants matched"}
        assert any(
            "multiple tenants match" in rec.message for rec in caplog.records
        ), caplog.text
    finally:
        _update_tenant_settings(snapshot["gelita"]["id"], snapshot["gelita"]["settings"])
        _update_tenant_settings(snapshot["t3ra"]["id"], snapshot["t3ra"]["settings"])
