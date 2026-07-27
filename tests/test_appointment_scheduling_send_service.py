"""Tests for appointment scheduling send router and send service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.services.appointment_scheduling.send_service import (
    SendConflictError,
    SendService,
)
from app.workflows.graph.routers import appointment_post_read_router

_TENANT_UUID = "11111111-1111-1111-1111-111111111111"


def _state(**data):
    return SimpleNamespace(data=data)


def test_post_read_router_routes_send_when_eligible() -> None:
    route = appointment_post_read_router(
        _state(
            event_type="appointment_draft_send",
            workflow_lifecycle_status="pending_review",
            workflow_lifecycle_sub_status="appointment_draft_created",
            email_draft={
                "to": "wh@example.com",
                "subject": "DEL APPT",
                "full_html": "<p>Hi</p>",
            },
        )
    )
    assert route == "send"


def test_post_read_router_end_when_already_sent() -> None:
    route = appointment_post_read_router(
        _state(
            event_type="appointment_draft_send",
            workflow_lifecycle_status="pending_review",
            workflow_lifecycle_sub_status="awaiting_customer_reply",
            email_draft={"to": "a@b.com", "subject": "s", "full_html": "b"},
        )
    )
    assert route == "end"


def test_post_read_router_intake_for_turvo_event() -> None:
    route = appointment_post_read_router(
        _state(event_type="turvo_pickup_changed")
    )
    assert route == "intake"


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_conflict_when_claim_conflict(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.claim_appointment_draft_send_queued.return_value = "conflict"
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"id": _TENANT_UUID}
    svc = SendService(
        lifecycle_service=lifecycle,
        tenants_service=tenants,
    )

    with pytest.raises(SendConflictError):
        svc.validate_and_enqueue_draft_send(
            tenant_slug="t3ra",
            workflow_lifecycle_id="wl-1",
            actor_user_id="user-1",
        )

    mock_enqueue.assert_not_called()
    lifecycle.claim_appointment_draft_send_queued.assert_called_once_with(
        lifecycle_id="wl-1",
        expected_tenant_id=_TENANT_UUID,
    )


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_enqueues_when_claim_wins(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.claim_appointment_draft_send_queued.return_value = "claimed"
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"id": _TENANT_UUID}
    mock_enqueue.return_value = "task-1"
    svc = SendService(
        lifecycle_service=lifecycle,
        tenants_service=tenants,
    )

    task_id = svc.validate_and_enqueue_draft_send(
        tenant_slug="t3ra",
        workflow_lifecycle_id="wl-1",
        actor_user_id="user-1",
    )

    assert task_id == "task-1"
    mock_enqueue.assert_called_once()


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_second_claim_does_not_enqueue(mock_enqueue: MagicMock) -> None:
    """Dual portal send: first claim wins and enqueues; second gets conflict."""
    lifecycle = MagicMock()
    lifecycle.claim_appointment_draft_send_queued.side_effect = ["claimed", "conflict"]
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"id": _TENANT_UUID}
    mock_enqueue.return_value = "exec-1"
    svc = SendService(
        lifecycle_service=lifecycle,
        tenants_service=tenants,
    )

    first = svc.validate_and_enqueue_draft_send(
        tenant_slug="t3ra",
        workflow_lifecycle_id="wl-1",
        actor_user_id="user-1",
    )
    assert first == "exec-1"

    with pytest.raises(SendConflictError):
        svc.validate_and_enqueue_draft_send(
            tenant_slug="t3ra",
            workflow_lifecycle_id="wl-1",
            actor_user_id="user-1",
        )

    assert mock_enqueue.call_count == 1
    assert lifecycle.claim_appointment_draft_send_queued.call_count == 2


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_rejects_other_tenant_lifecycle(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.claim_appointment_draft_send_queued.return_value = "not_found"
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"id": _TENANT_UUID}
    svc = SendService(
        lifecycle_service=lifecycle,
        tenants_service=tenants,
    )

    with pytest.raises(ValueError, match="lifecycle_not_found"):
        svc.validate_and_enqueue_draft_send(
            tenant_slug="t3ra",
            workflow_lifecycle_id="wl-1",
            actor_user_id="user-1",
        )

    mock_enqueue.assert_not_called()


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_missing_email_draft(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.claim_appointment_draft_send_queued.return_value = "scheduling_draft_not_ready"
    tenants = MagicMock()
    tenants.get_by_slug.return_value = {"id": _TENANT_UUID}
    svc = SendService(
        lifecycle_service=lifecycle,
        tenants_service=tenants,
    )

    with pytest.raises(ValueError, match="scheduling_draft_not_ready"):
        svc.validate_and_enqueue_draft_send(
            tenant_slug="t3ra",
            workflow_lifecycle_id="wl-1",
            actor_user_id="user-1",
        )

    mock_enqueue.assert_not_called()


@patch("app.services.appointment_scheduling.send_service.LifecycleRunSerializerService")
def test_enqueue_appointment_draft_send_uses_serializer(mock_serializer_cls: MagicMock) -> None:
    from app.services.appointment_scheduling.send_service import enqueue_appointment_draft_send

    mock_serializer_cls.return_value.enqueue.return_value = MagicMock(
        status="started",
        celery_task_id="celery-abc",
        lifecycle_id="wl-1",
    )

    execution_id = enqueue_appointment_draft_send(
        tenant_slug="t3ra",
        payload={
            "tenant_id": _TENANT_UUID,
            "workflow_lifecycle_id": "wl-1",
            "actor_user_id": "user-1",
        },
    )

    assert execution_id
    mock_serializer_cls.return_value.enqueue.assert_called_once()
    call_kwargs = mock_serializer_cls.return_value.enqueue.call_args.kwargs
    assert call_kwargs["tenant_slug"] == "t3ra"
    assert call_kwargs["workflow_name"] == "appointment_scheduling"
    assert call_kwargs["payload"]["event_type"] == "appointment_draft_send"
    assert call_kwargs["payload"]["workflow_lifecycle_id"] == "wl-1"
    assert call_kwargs["payload"]["execution_id"] == execution_id
