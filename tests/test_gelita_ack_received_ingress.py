"""Gelita ack_received ingress: skip workflow when lifecycle already completed."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import status
from fastapi.responses import JSONResponse

from app.services.gelita_inbound_email_service import GelitaInboundEmailService
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_ID = "11111111-1111-1111-1111-111111111111"
COMM_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
THREAD_ID = "thread-ack-1"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
    )


def _reply_payload() -> dict:
    return {
        "thread_id": THREAD_ID,
        "email_id": "unipile-email-ack-1",
        "in_reply_to": "<msg-parent@example.com>",
        "body": "We accept the load.",
    }


@patch("app.services.gelita_inbound_email_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_skips_enqueue_when_lifecycle_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "completed",
        "sub_status": "accepted",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    response = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "lifecycle completed; ack not processed"
    assert content["event_type"] == "ack_received"
    assert content["workflow_lifecycle_id"] == LIFECYCLE_ID
    assert "execution_id" not in content
    mock_enqueue.assert_not_called()


@patch("app.services.gelita_inbound_email_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_enqueues_when_lifecycle_not_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "tender_sent_to_carrier",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    mock_enqueue.return_value = "exec-ack-1"

    response = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["event_type"] == "ack_received"
    assert content["execution_id"] == "exec-ack-1"
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["event_type"] == "ack_received"
    wp = mock_enqueue.call_args.kwargs["payload"]
    assert wp["workflow_lifecycle_id"] == LIFECYCLE_ID
    assert wp["tender_id"] == "22222222-2222-2222-2222-222222222222"
    assert wp["communication_id"] == COMM_ID
    assert mock_enqueue.call_args.kwargs["communication_id"] == COMM_ID
    assert mock_enqueue.call_args.kwargs["thread_id"] == THREAD_ID


@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_returns_none_when_thread_unlinked() -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._communications.resolve_lifecycle_id_for_thread.return_value = None

    response = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )
    assert response is None


@pytest.mark.asyncio
@patch("app.services.gelita_inbound_email_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
async def test_handle_records_comms_but_skips_ack_when_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "completed",
        "sub_status": "accepted",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }
    svc._communications.record_or_resolve_inbound.return_value = COMM_ID

    with patch(
        "app.services.gelita_inbound_email_service.resolve_workflow_graph_tenant_id",
        return_value="gelita",
    ):
        response = await svc.handle(
            payload=_reply_payload(),
            tenant=_tenant(),
        )

    svc._communications.record_or_resolve_inbound.assert_called_once()
    mock_enqueue.assert_not_called()
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "lifecycle completed; ack not processed"
