"""Tests for TeamsNotificationService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState
from app.integrations.teams.webhook import TeamsWebhookError
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.appointment_scheduling.teams_notification_service import (
    TeamsNotificationService,
)


def _state(**data_overrides) -> WorkflowState:
    data = {
        "event_type": WorkflowRunEventType.TURVO_PICKUP_CHANGED.value,
        "workflow_lifecycle_id": "11111111-2222-3333-4444-555555555555",
        "load_id": "62396",
        "reference_number": "DIAMOND-1",
        "customer_name": "BUCHANAN",
        "llm_appointment_decision": {
            "selected_pickup_date": "07/01/2026",
            "calculated_delivery_date": "07/04/2026",
        },
        "email_draft": {
            "to": "wh@example.com",
            "subject": 'DEL APPT REQ "62396"',
            "full_html": "<p>draft</p>",
        },
        "tenant_settings": {
            "appointment_scheduling": {
                "teams_notification": {
                    "teams_webhook_url": "https://example.invalid/webhook",
                },
            },
        },
    }
    data.update(data_overrides)
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        execution_id="run-1",
        data=data,
    )


def test_notify_skips_when_no_settings() -> None:
    activity = MagicMock()
    svc = TeamsNotificationService(activity_service=activity)

    result = svc.notify_from_state(_state(tenant_settings={}))

    assert result.skipped is True
    assert result.skip_reason == "no_teams_notification_settings"
    activity.record_draft_teams_notification.assert_not_called()


def test_notify_skips_when_not_intake_event() -> None:
    activity = MagicMock()
    svc = TeamsNotificationService(activity_service=activity)

    result = svc.notify_from_state(
        _state(event_type=WorkflowRunEventType.APPOINTMENT_DRAFT_SEND.value)
    )

    assert result.skipped is True
    assert result.skip_reason == "not_intake_event"
    activity.record_draft_teams_notification.assert_not_called()


@patch(
    "app.services.appointment_scheduling.teams_notification_service.post_message_card_sync",
)
def test_notify_success_posts_and_records_activity(mock_post: MagicMock) -> None:
    activity = MagicMock()
    svc = TeamsNotificationService(activity_service=activity)
    state = _state()

    result = svc.notify_from_state(state)

    assert result.sent is True
    mock_post.assert_called_once()
    activity.record_draft_teams_notification.assert_called_once_with(state)


@patch(
    "app.services.appointment_scheduling.teams_notification_service.post_message_card_sync",
)
def test_notify_webhook_error_is_non_fatal(mock_post: MagicMock) -> None:
    mock_post.side_effect = TeamsWebhookError("failed", status_code=500)
    activity = MagicMock()
    svc = TeamsNotificationService(activity_service=activity)

    result = svc.notify_from_state(_state())

    assert result.error == "teams_post_failed"
    assert result.sent is False
    activity.record_draft_teams_notification.assert_not_called()
