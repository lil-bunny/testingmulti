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
_OTHER_TENANT_UUID = "00000000-0000-0000-0000-000000000000"


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
def test_send_service_conflict_when_not_draft_created(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "status": "pending_review",
        "sub_status": "awaiting_customer_reply",
        "metadata": {
            "email_draft": {
                "to": "wh@example.com",
                "subject": "DEL APPT",
                "full_html": "<p>Hi</p>",
            }
        },
    }
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


@patch("app.services.appointment_scheduling.send_service.enqueue_appointment_draft_send")
def test_send_service_enqueues_when_draft_created(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _TENANT_UUID,
        "status": "pending_review",
        "sub_status": "appointment_draft_created",
        "metadata": {
            "email_draft": {
                "to": "wh@example.com",
                "subject": "DEL APPT",
                "full_html": "<p>Hi</p>",
            }
        },
    }
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
def test_send_service_rejects_other_tenant_lifecycle(mock_enqueue: MagicMock) -> None:
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "tenant_id": _OTHER_TENANT_UUID,
        "status": "pending_review",
        "sub_status": "appointment_draft_created",
        "metadata": {
            "email_draft": {
                "to": "wh@example.com",
                "subject": "DEL APPT",
                "full_html": "<p>Hi</p>",
            }
        },
    }
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
