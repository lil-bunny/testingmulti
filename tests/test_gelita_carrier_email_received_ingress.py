"""Gelita carrier_email_received ingress: inbox role only."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.gelita_email_ingress_service import (
    GelitaCarrierEmailIngressError,
    GelitaEmailIngressService,
)
from app.services.unipile_tenant_resolution import UnipileTenantContext

TENANT_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
LIFECYCLE_ID = "11111111-1111-1111-1111-111111111111"
TENDER_ID = "22222222-2222-2222-2222-222222222222"
COMM_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"
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


def _service_with_mocks(*, load_type: str = "FTL", attempt: int = 1) -> GelitaEmailIngressService:
    svc = GelitaEmailIngressService()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()
    svc._communications = MagicMock()
    svc._communications.is_thread_linked_to_lifecycle.return_value = False
    svc._communications.find_linked_thread_for_lifecycle.return_value = None
    svc._communications.is_communication_linked_to_run.return_value = False
    svc._communications.is_retired_carrier_thread.return_value = False
    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": TENDER_ID,
        "order_number": "93795",
        "load_type": load_type,
    }
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "tender_id": TENDER_ID,
        "status": "processing",
        "metadata": {"routing_guide_attempt": attempt},
    }
    return svc


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_skips_non_inbox_role() -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="drafts"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert response.outcome == "no_match"
    assert "non-inbox" in (response.reason or "")
    svc._tender_service.find_tender_by_order_number.assert_not_called()
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_not_called()


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_skips_sent_role() -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="sent"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert response.outcome == "no_match"
    assert "non-inbox" in (response.reason or "")
    svc._tender_service.find_tender_by_order_number.assert_not_called()
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_not_called()


@patch(
    "app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link",
    return_value="exec-carrier-1",
)
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_enqueues_for_inbox_role(
    mock_enqueue: MagicMock,
) -> None:
    svc = _service_with_mocks()

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="inbox"),
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert response.outcome == "enqueued"
    assert response.event_type == "carrier_email_received"
    assert response.execution_ids == ("exec-carrier-1",)
    mock_enqueue.assert_called_once()
    call_kwargs = mock_enqueue.call_args.kwargs
    assert call_kwargs["event_type"] == "carrier_email_received"
    assert call_kwargs["payload"]["order_number"] == "93795"
    assert call_kwargs["payload"]["communication_id"] == COMM_ID
    assert call_kwargs["communication_id"] == COMM_ID
    assert call_kwargs["thread_id"] == THREAD_ID
    assert call_kwargs["routing_guide_attempt"] == 1
    assert call_kwargs["payload"]["routing_guide_attempt"] == 1
    svc._tender_service.find_tender_by_order_number.assert_called_once_with(
        tenant_id=TENANT_UUID,
        order_number="93795",
    )
    svc._lifecycle.find_lifecycle_row_by_tender_id.assert_called_once_with(
        tenant_id=TENANT_UUID,
        workflow_name="load_tendering",
        tender_id=TENDER_ID,
    )
    svc._communications.is_thread_linked_to_lifecycle.assert_called_once()
    svc._communications.find_linked_thread_for_lifecycle.assert_called_once()


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_skips_when_thread_already_linked() -> None:
    svc = _service_with_mocks()
    svc._communications.is_thread_linked_to_lifecycle.return_value = True

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="inbox"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert response.outcome == "skipped"
    assert response.reason == "carrier thread already linked"


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_raises_when_tender_missing() -> None:
    svc = _service_with_mocks()
    svc._tender_service.find_tender_by_order_number.return_value = None

    with pytest.raises(GelitaCarrierEmailIngressError, match="no tender for order_number"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
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
    "app.services.gelita_email_ingress_service.resolve_workflow_graph_tenant_id",
    return_value="gelita",
)
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
async def test_process_skips_when_no_order_number(
    _resolve_graph: MagicMock,
) -> None:
    svc = GelitaEmailIngressService()
    svc._communications = MagicMock()
    svc._lifecycle = MagicMock()
    svc._tender_service = MagicMock()

    result = await svc.process(
        payload={
            "role": "inbox",
            "thread_id": THREAD_ID,
            "body": "Thanks, we will review.",
        },
        tenant=_tenant(),
        communication_id=COMM_ID,
    )

    assert result.outcome == "skipped"
    assert result.event_type == "carrier_email_received"
    assert result.reason is not None
    assert "no order number" in result.reason
    svc._tender_service.find_tender_by_order_number.assert_not_called()


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_raises_on_thread_conflict() -> None:
    svc = _service_with_mocks()
    svc._communications.find_linked_thread_for_lifecycle.return_value = "other-thread"

    with pytest.raises(GelitaCarrierEmailIngressError, match="carrier thread conflict"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )


@patch(
    "app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link",
    return_value="exec-carrier-2",
)
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_allows_attempt_2_thread(mock_enqueue: MagicMock) -> None:
    svc = _service_with_mocks(attempt=2)
    svc._communications.find_linked_thread_for_lifecycle.return_value = None

    response = svc._carrier_email_received(
        payload={**_carrier_payload(role="inbox"), "thread_id": "carrier-2-thread"},
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert response.outcome == "enqueued"
    assert response.execution_ids == ("exec-carrier-2",)
    mock_enqueue.assert_called_once()
    assert mock_enqueue.call_args.kwargs["routing_guide_attempt"] == 2
    svc._communications.is_thread_linked_to_lifecycle.assert_called_once()
    assert (
        svc._communications.is_thread_linked_to_lifecycle.call_args.kwargs[
            "routing_guide_attempt"
        ]
        == 2
    )


@patch(
    "app.services.gelita_email_ingress_service.enqueue_gelita_load_tendering_and_link",
    return_value="exec-carrier-2",
)
@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_ftl_resolves_load_type_without_repo_field(
    mock_enqueue: MagicMock,
) -> None:
    """Regression: order lookup without load_type must still take FTL attempt-scoped path."""
    svc = _service_with_mocks(attempt=2)
    svc._tender_service.find_tender_by_order_number.return_value = {
        "id": TENDER_ID,
        "order_number": "93795",
    }
    svc._tender_service.read_order.return_value = {
        "tender": {"load_type": "FTL"},
        "products": [],
    }
    svc._communications.find_linked_thread_for_lifecycle.return_value = None

    response = svc._carrier_email_received(
        payload={**_carrier_payload(role="inbox"), "thread_id": "carrier-2-thread"},
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert response.outcome == "enqueued"
    assert response.execution_ids == ("exec-carrier-2",)
    svc._tender_service.read_order.assert_called_once()
    assert (
        svc._communications.find_linked_thread_for_lifecycle.call_args.kwargs[
            "routing_guide_attempt"
        ]
        == 2
    )


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_skips_completed_lifecycle() -> None:
    svc = _service_with_mocks()
    svc._lifecycle.find_lifecycle_row_by_tender_id.return_value = {
        "id": LIFECYCLE_ID,
        "tender_id": TENDER_ID,
        "status": "completed",
        "metadata": {"routing_guide_attempt": 1},
    }

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="inbox"),
        tenant=_tenant(),
        graph_slug="gelita",
    )

    assert response.outcome == "skipped"
    assert response.reason == "lifecycle_completed"


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_skips_when_comm_already_linked() -> None:
    svc = _service_with_mocks()
    svc._communications.is_communication_linked_to_run.return_value = True

    response = svc._carrier_email_received(
        payload=_carrier_payload(role="inbox"),
        tenant=_tenant(),
        graph_slug="gelita",
        communication_id=COMM_ID,
    )

    assert response.outcome == "skipped"
    assert response.reason == "communication already linked"


@patch.object(GelitaEmailIngressService, "__init__", lambda self: None)
def test_carrier_email_received_ltl_uses_global_thread_conflict() -> None:
    svc = _service_with_mocks(load_type="LTL")
    svc._communications.find_linked_thread_for_lifecycle.return_value = "other-thread"

    with pytest.raises(GelitaCarrierEmailIngressError, match="carrier thread conflict"):
        svc._carrier_email_received(
            payload=_carrier_payload(role="inbox"),
            tenant=_tenant(),
            graph_slug="gelita",
        )

    assert (
        svc._communications.find_linked_thread_for_lifecycle.call_args.kwargs.get(
            "routing_guide_attempt"
        )
        is None
    )
