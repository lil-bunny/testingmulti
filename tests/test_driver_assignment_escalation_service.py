"""Tests for driver assignment Teams escalation service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.services.driver_assignment.escalation_service import DriverAssignmentEscalationService
from app.services.driver_assignment.ingress_service import EligibilityResult
from tests.test_turvo_driver_request_eligibility import _eligible_payload


_TENANT_SETTINGS = {
    "driver_assignment": {
        "reminders": {"skip_sub_statuses": ["details_received", "uploaded_to_tms", "escalated"]},
        "escalate_driver": {
            "teams_webhook_url": "https://example.webhook.office.com/test",
            "message_title": "Escalation load {load_id}",
        },
    }
}

_BASE_PAYLOAD = {
    "event_type": "escalation_due",
    "tenant_id": "tenant-1",
    "workflow_lifecycle_id": "wl-1",
    "load_id": "30389",
    "shipment_id": "1000324895",
    "shipments_row_id": "ship-row-1",
    "tenant_settings": _TENANT_SETTINGS,
    "shipment": _eligible_payload(),
}


def test_escalate_skipped_when_ingress_ineligible() -> None:
    ingress = MagicMock()
    ingress.check_escalation_eligibility.return_value = EligibilityResult(
        skip_reason="driver_already_assigned"
    )
    svc = DriverAssignmentEscalationService(ingress_service=ingress)

    result = svc.escalate_from_payload(
        tenant_id="tenant-1",
        tenant_settings=_TENANT_SETTINGS,
        payload=_BASE_PAYLOAD,
    )

    assert result.skipped is True
    assert result.skip_reason == "driver_already_assigned"
    ingress.check_escalation_eligibility.assert_called_once()


def test_escalate_posts_teams_and_records_activity() -> None:
    ingress = MagicMock()
    ingress.check_escalation_eligibility.return_value = EligibilityResult(skip_reason=None)
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "reminder_4_sent",
    }
    activity = MagicMock()

    svc = DriverAssignmentEscalationService(
        ingress_service=ingress,
        activity_service=activity,
        lifecycle_service=lifecycle,
    )

    with patch(
        "app.services.driver_assignment.escalation_service.post_message_card",
        new_callable=AsyncMock,
    ) as post_mock:
        result = svc.escalate_from_payload(
            tenant_id="tenant-1",
            tenant_settings=_TENANT_SETTINGS,
            payload=_BASE_PAYLOAD,
            workflow_run_id="run-1",
        )

    assert result.sent is True
    post_mock.assert_awaited_once()
    _args, kwargs = post_mock.await_args
    fact_labels = [label for label, _ in kwargs["facts"]]
    assert "Shipments row ID" not in fact_labels
    assert "Lifecycle ID" not in fact_labels
    assert "Current sub-status" not in fact_labels
    activity.record_escalation_sent.assert_called_once()


def test_escalate_shadow_still_posts_teams() -> None:
    ingress = MagicMock()
    ingress.check_escalation_eligibility.return_value = EligibilityResult(skip_reason=None)
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "reminder_4_sent",
    }
    activity = MagicMock()
    payload = {
        **_BASE_PAYLOAD,
        "workflow_shadow_mode": True,
    }

    svc = DriverAssignmentEscalationService(
        ingress_service=ingress,
        activity_service=activity,
        lifecycle_service=lifecycle,
    )

    with patch(
        "app.services.driver_assignment.escalation_service.post_message_card",
        new_callable=AsyncMock,
    ) as post_mock:
        result = svc.escalate_from_payload(
            tenant_id="tenant-1",
            tenant_settings=_TENANT_SETTINGS,
            payload=payload,
            workflow_run_id="run-1",
        )

    assert result.sent is True
    post_mock.assert_awaited_once()
    activity.record_escalation_sent.assert_called_once()


def test_escalate_returns_error_when_teams_fails() -> None:
    from app.integrations.teams.webhook import TeamsWebhookError

    ingress = MagicMock()
    ingress.check_escalation_eligibility.return_value = EligibilityResult(skip_reason=None)
    lifecycle = MagicMock()
    lifecycle.read_lifecycle_row_by_id.return_value = {
        "status": "processing",
        "sub_status": "reminder_4_sent",
    }

    svc = DriverAssignmentEscalationService(
        ingress_service=ingress,
        lifecycle_service=lifecycle,
    )

    with patch(
        "app.services.driver_assignment.escalation_service.post_message_card",
        new_callable=AsyncMock,
        side_effect=TeamsWebhookError("fail", status_code=500),
    ):
        result = svc.escalate_from_payload(
            tenant_id="tenant-1",
            tenant_settings=_TENANT_SETTINGS,
            payload=_BASE_PAYLOAD,
        )

    assert result.error == "teams_post_failed"
