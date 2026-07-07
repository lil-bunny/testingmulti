"""Order rollover: repeat order numbers create new tenders; latest row wins on lookup."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from fastapi.responses import JSONResponse

from app.repositories.tenders_repository import TendersRepository
from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NEW_TENDER_ID = "22222222-2222-2222-2222-222222222222"
OLD_TENDER_ID = "44444444-4444-4444-4444-444444444444"
LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"
COMM_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(tenant_uuid=TENANT_UUID, tenant_slug="gelita")


def test_get_by_order_number_sql_orders_by_created_at_desc() -> None:
    """Latest-tender lookup must sort by ``created_at``, not ``updated_at``."""
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    repo = TendersRepository(session)

    repo.get_by_order_number(tenant_id=TENANT_UUID, order_number="93384")

    sql = str(session.execute.call_args[0][0])
    assert "created_at DESC" in sql
    assert "load_type" in sql


def test_carrier_ingress_resolves_lifecycle_for_latest_tender_id() -> None:
    """Carrier email ingress binds to the tender returned by order-number lookup."""
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()

    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": NEW_TENDER_ID,
        "order_number": "93795",
    }
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "tender_id": NEW_TENDER_ID,
    }

    order_number, thread_id, lifecycle_id, tender_id, _row, _tender = (
        svc._find_lifecycle_row_by_order_number(
            payload={
                "body": "<p>Order #93795</p>",
                "thread_id": "thread-1",
            },
            tenant_id=TENANT_UUID,
        )
    )

    assert order_number == "93795"
    assert thread_id == "thread-1"
    assert lifecycle_id == LIFECYCLE_ID
    assert tender_id == NEW_TENDER_ID
    svc._tender_service.find_tender_by_order_number.assert_called_once_with(
        tenant_id=TENANT_UUID,
        order_number="93795",
    )
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_called_once_with(
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        tender_id=NEW_TENDER_ID,
    )


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_skips_stale_order_rollover_on_old_thread() -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._tender_service = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "tender_id": OLD_TENDER_ID,
        "metadata": {"routing_guide_attempt": 1},
    }
    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": NEW_TENDER_ID,
        "load_type": "FTL",
    }

    response = svc._try_ack_received(
        payload={
            "thread_id": "old-thread",
            "in_reply_to": "<parent@example.com>",
            "body": "<p>Order #93795 — accepted</p>",
        },
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    content = json.loads(response.body)
    assert content["reason"] == "stale_order_rollover"


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_ingress_skips_when_lifecycle_tender_mismatch() -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()
    svc._communications = MagicMock()
    svc._communications.is_thread_linked_to_lifecycle.return_value = False
    svc._communications.find_linked_thread_for_lifecycle.return_value = None
    svc._communications.is_communication_linked_to_run.return_value = False

    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": NEW_TENDER_ID,
        "load_type": "FTL",
    }
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "tender_id": OLD_TENDER_ID,
        "status": "processing",
        "metadata": {"routing_guide_attempt": 1},
    }

    response = svc._carrier_email_received(
        payload={
            "role": "inbox",
            "thread_id": "thread-1",
            "body": "<p>Order #93795</p>",
        },
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    content = json.loads(response.body)
    assert content["reason"] == "stale_order_rollover"
