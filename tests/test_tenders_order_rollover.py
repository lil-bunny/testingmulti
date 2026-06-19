"""Order rollover: repeat order numbers create new tenders; latest row wins on lookup."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.repositories.tenders_repository import TendersRepository
from app.services.gelita_inbound_email_service import GelitaInboundEmailService

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
NEW_TENDER_ID = "22222222-2222-2222-2222-222222222222"
LIFECYCLE_ID = "33333333-3333-3333-3333-333333333333"


def test_get_by_order_number_sql_orders_by_created_at_desc() -> None:
    """Latest-tender lookup must sort by ``created_at``, not ``updated_at``."""
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    repo = TendersRepository(session)

    repo.get_by_order_number(tenant_id=TENANT_UUID, order_number="93384")

    sql = str(session.execute.call_args[0][0])
    assert "created_at DESC" in sql


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

    order_number, thread_id, lifecycle_id, tender_id, _row = (
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
