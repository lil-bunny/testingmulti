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
THREAD_ID = "thread-ack-1"


def _tenant() -> UnipileTenantContext:
    return UnipileTenantContext(
        tenant_uuid=TENANT_UUID,
        tenant_slug="gelita",
    )


def _reply_payload() -> dict:
    return {
        "thread_id": THREAD_ID,
        "in_reply_to": "<msg-parent@example.com>",
        "body": "We accept the load.",
    }


@patch("app.services.gelita_inbound_email_service.run_workflow_async")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_skips_enqueue_when_lifecycle_completed(
    mock_celery: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._lifecycle.read_lifecycle.return_value = {
        "found": True,
        "lifecycle_id": LIFECYCLE_ID,
    }
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
    mock_celery.apply_async.assert_not_called()


@patch("app.services.gelita_inbound_email_service.run_workflow_async")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
def test_ack_received_enqueues_when_lifecycle_not_completed(
    mock_celery: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._lifecycle.read_lifecycle.return_value = {
        "found": True,
        "lifecycle_id": LIFECYCLE_ID,
    }
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "tender_sent_to_carrier",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    mock_task = MagicMock()
    mock_task.apply_async.return_value = MagicMock(id="celery-ack-1")
    mock_celery.apply_async = mock_task.apply_async

    response = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(response, JSONResponse)
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["event_type"] == "ack_received"
    assert content["execution_id"]
    assert mock_task.apply_async.call_count == 1
    wp = mock_task.apply_async.call_args.kwargs["kwargs"]["payload"]
    assert wp["event_type"] == "ack_received"
    assert wp["workflow_lifecycle_id"] == LIFECYCLE_ID
    assert wp["tender_id"] == "22222222-2222-2222-2222-222222222222"


@pytest.mark.asyncio
@patch("app.services.gelita_inbound_email_service.run_workflow_async")
@patch.object(GelitaInboundEmailService, "__init__", lambda self: None)
async def test_handle_records_comms_but_skips_ack_when_completed(
    mock_celery: MagicMock,
) -> None:
    svc = GelitaInboundEmailService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._lifecycle.read_lifecycle.return_value = {
        "found": True,
        "lifecycle_id": LIFECYCLE_ID,
    }
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "completed",
        "sub_status": "accepted",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    with patch(
        "app.services.gelita_inbound_email_service.resolve_workflow_graph_tenant_id",
        return_value="gelita",
    ):
        response = await svc.handle(
            payload=_reply_payload(),
            tenant=_tenant(),
        )

    svc._communications.record_inbound.assert_called_once()
    mock_celery.apply_async.assert_not_called()
    assert response.status_code == status.HTTP_200_OK
    content = json.loads(response.body)
    assert content["message"] == "lifecycle completed; ack not processed"
