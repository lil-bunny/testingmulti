"""Gelita ack_received ingress: skip workflow when lifecycle already completed."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domain.ingress_result import IngressResult
from app.services.gelita_email_ingress_service import GelitaEmailIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext
from tests.fixtures.outlook_auto_reply_emails import ack_received_ooo_webhook_payload

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


@patch("app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_ack_received_skips_enqueue_when_lifecycle_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "completed",
        "sub_status": "accepted",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    result = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert isinstance(result, IngressResult)
    assert result.outcome == "skipped"
    assert result.event_type == "ack_received"
    assert result.reason == "lifecycle completed; ack not processed"
    assert result.execution_ids == ()
    mock_enqueue.assert_not_called()


@patch("app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_ack_received_skips_retired_carrier_thread(mock_enqueue: MagicMock) -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._tender_service = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "tender_id": "22222222-2222-2222-2222-222222222222",
        "metadata": {"routing_guide_attempt": 3},
    }
    svc._tender_service.read_order.return_value = {
        "tender": {"load_type": "FTL"},
        "products": [],
    }
    svc._communications.is_retired_carrier_thread.return_value = True

    result = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert result is not None
    assert result.outcome == "skipped"
    assert result.reason == "retired_carrier_thread"
    mock_enqueue.assert_not_called()


@patch("app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_ack_received_enqueues_when_lifecycle_not_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._tender_service = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "tender_sent_to_carrier",
        "tender_id": "22222222-2222-2222-2222-222222222222",
        "metadata": {"routing_guide_attempt": 1},
    }
    svc._tender_service.read_order.return_value = {
        "tender": {"load_type": "LTL"},
        "products": [],
    }
    svc._communications.is_communication_linked_to_run.return_value = False

    mock_enqueue.return_value = "exec-ack-1"

    result = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert isinstance(result, IngressResult)
    assert result.outcome == "enqueued"
    assert result.event_type == "ack_received"
    assert result.execution_ids == ("exec-ack-1",)
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["event_type"] == "ack_received"
    wp = mock_enqueue.call_args.kwargs["payload"]
    assert wp["workflow_lifecycle_id"] == LIFECYCLE_ID
    assert wp["tender_id"] == "22222222-2222-2222-2222-222222222222"
    assert wp["communication_id"] == COMM_ID
    assert mock_enqueue.call_args.kwargs["communication_id"] == COMM_ID
    assert mock_enqueue.call_args.kwargs["thread_id"] == THREAD_ID


@patch("app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_ack_received_enqueues_automatic_reply_for_worker_guard(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._tender_service = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "tender_sent_to_carrier",
        "tender_id": "22222222-2222-2222-2222-222222222222",
        "metadata": {"routing_guide_attempt": 1},
    }
    svc._tender_service.read_order.return_value = {
        "tender": {"load_type": "LTL"},
        "products": [],
    }
    svc._communications.is_communication_linked_to_run.return_value = False
    mock_enqueue.return_value = "exec-ooo-1"

    result = svc._try_ack_received(
        payload=ack_received_ooo_webhook_payload(thread_id=THREAD_ID),
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert isinstance(result, IngressResult)
    assert result.outcome == "enqueued"
    assert result.execution_ids == ("exec-ooo-1",)
    mock_enqueue.assert_called_once()
    wp = mock_enqueue.call_args.kwargs["payload"]
    assert wp["subject"].startswith("Automatic reply:")


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_ack_received_returns_none_when_thread_unlinked() -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()
    svc._communications.resolve_lifecycle_id_for_thread.return_value = None

    result = svc._try_ack_received(
        payload=_reply_payload(),
        tenant=_tenant(),
        graph_slug="gelita",
    )
    assert result is None


@pytest.mark.asyncio
@patch("app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link")
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
async def test_process_skips_ack_when_lifecycle_completed(
    mock_enqueue: MagicMock,
) -> None:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._communications = MagicMock()

    svc._communications.resolve_lifecycle_id_for_thread.return_value = LIFECYCLE_ID
    svc._lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "completed",
        "sub_status": "accepted",
        "tender_id": "22222222-2222-2222-2222-222222222222",
    }

    with patch(
        "app.services.gelita_email_ingress_service.resolve_workflow_graph_tenant_id",
        return_value="gelita",
    ):
        result = await svc.process(
            payload=_reply_payload(),
            tenant=_tenant(),
            communication_id=COMM_ID,
        )

    mock_enqueue.assert_not_called()
    assert result.outcome == "skipped"
    assert result.reason == "lifecycle completed; ack not processed"
