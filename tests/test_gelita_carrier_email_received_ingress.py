"""Gelita carrier_email_received ingress: inbox role only."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.responses import JSONResponse

from app.services.gelita_inbound_email_service import (
    GelitaCarrierEmailIngressError,
    GelitaInboundEmailService,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_ID = "11111111-1111-1111-1111-111111111111"
TENDER_ID = "22222222-2222-2222-2222-222222222222"
THREAD_ID = "thread-carrier-1"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
    )


def _carrier_payload(*, role: str = "inbox") -> dict:
    return {
        "role": role,
        "folders": ["Drafts"] if role == "drafts" else ["Inbox"],
        "thread_id": THREAD_ID,
        "body": "<p>Order #93795</p>",
    }


def _service_with_mocks() -> GelitaInboundEmailService:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()
    svc._communications = MagicMock()
    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": TENDER_ID,
        "order_number": "93795",
    }
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "email_thread_id": None,
        "tender_id": TENDER_ID,
    }
    return svc


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_skips_non_inbox_role() -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="drafts"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "non-inbox email; carrier workflow not queued"
    svc._tender_service.find_tender_by_order_number.assert_not_called()
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_not_called()


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_skips_sent_role() -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="sent"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    content = json.loads(response.body)
    assert content["message"] == "non-inbox email; carrier workflow not queued"
    svc._tender_service.find_tender_by_order_number.assert_not_called()
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_not_called()


@patch(
    "app.services.gelita_inbound_email_service.enqueue_load_tendering_workflow",
    return_value="exec-carrier-1",
)
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_enqueues_for_inbox_role(
    mock_enqueue: MagicMock,
) -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="inbox"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    content = json.loads(response.body)
    assert content["event_type"] == "carrier_email_received"
    assert content["execution_id"] == "exec-carrier-1"
    mock_enqueue.assert_called_once()
    call_kwargs = mock_enqueue.call_args.kwargs
    assert call_kwargs["event_type"] == "carrier_email_received"
    assert call_kwargs["payload"]["order_number"] == "93795"
    svc._tender_service.find_tender_by_order_number.assert_called_once_with(
        tenant_id=TENANT_UUID,
        order_number="93795",
    )
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_called_once_with(
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        tender_id=TENDER_ID,
    )
    svc._lifecycle.set_email_thread_id.assert_called_once_with(
        lifecycle_id=LIFECYCLE_ID,
        thread_id=THREAD_ID,
    )


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_raises_when_tender_missing() -> None:
    svc = _service_with_mocks()
    svc._tender_service.find_tender_by_order_number.return_value = None

    with pytest.raises(GelitaCarrierEmailIngressError, match="no tender for order_number"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_raises_when_lifecycle_missing() -> None:
    svc = _service_with_mocks()
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = None

    with pytest.raises(GelitaCarrierEmailIngressError, match="no load_tendering lifecycle"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )


@pytest.mark.asyncio
@patch(
    "app.services.gelita_inbound_email_service.resolve_workflow_graph_tenant_id",
    return_value="gelita",
)
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
async def test_handle_returns_200_when_no_order_number(
    _resolve_graph: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._communications = MagicMock()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()

    response = await svc.handle(
        payload={
            "role": "inbox",
            "thread_id": THREAD_ID,
            "body": "Thanks, we will review.",
        },
        tenant=_tenant(),
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "skipped"
    assert content["event_type"] == "carrier_email_received"
    assert "no order number" in content["reason"]
    svc._tender_service.find_tender_by_order_number.assert_not_called()


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_carrier_email_received_raises_on_thread_conflict() -> None:
    svc = _service_with_mocks()
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "email_thread_id": "other-thread",
        "tender_id": TENDER_ID,
    }

    with pytest.raises(GelitaCarrierEmailIngressError, match="email_thread_id conflict"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )
