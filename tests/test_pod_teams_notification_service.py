"""Tests for POD analysis Teams notification service."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from app.domain.state import WorkflowState
from app.services.pod_lifecycle.teams_notification_service import (
    PodLifecycleTeamsNotificationService,
)

_TENANT_SETTINGS = {
    "pod_lifecycle": {
        "teams_notification": {
            "teams_webhook_url": "https://example.webhook.office.com/test",
            "message_title": "POD analyzed — Load {load_id}",
        },
    },
}

_BASE_DATA = {
    "event_type": "email_received",
    "workflow_lifecycle_id": "wl-1",
    "load_id": "30389",
    "tenant_settings": _TENANT_SETTINGS,
    "documents_pod": {"stored": True, "id": "doc-1"},
    "pod_merged_pdf_object_key": "pod_attachments/pod.pdf",
    "document_analysis_pod": {"stored": True, "id": "analysis-1"},
    "pod_scoring_results": {
        "success": True,
        "score": {
            "final_score": 87,
            "overall_status": "PASS",
            "po_scores": [{"po_number": "A1176371", "po_total": 87}],
            "exceptions": [],
            "remarks": [],
        },
    },
}


def _state(*, data: dict | None = None) -> WorkflowState:
    payload = dict(_BASE_DATA)
    if data:
        payload.update(data)
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="t3ra",
        execution_id="run-1",
        data=payload,
    )


def test_notify_skipped_when_no_settings() -> None:
    result = PodLifecycleTeamsNotificationService().notify_from_state(
        _state(data={"tenant_settings": {}})
    )
    assert result.skipped is True
    assert result.skip_reason == "no_teams_notification_settings"


def test_notify_skipped_when_analysis_not_stored() -> None:
    result = PodLifecycleTeamsNotificationService().notify_from_state(
        _state(data={"document_analysis_pod": {"stored": False}})
    )
    assert result.skipped is True
    assert result.skip_reason == "pod_analysis_not_stored"


def test_notify_posts_teams_on_success() -> None:
    with patch(
        "app.services.pod_lifecycle.teams_notification_service.post_message_card",
        new_callable=AsyncMock,
    ) as post_mock:
        result = PodLifecycleTeamsNotificationService().notify_from_state(_state())

    assert result.sent is True
    post_mock.assert_awaited_once()
    _url, kwargs = post_mock.await_args.args[0], post_mock.await_args.kwargs
    assert _url == "https://example.webhook.office.com/test"
    assert kwargs["title"] == "POD analyzed — Load 30389"
    facts = dict(kwargs["facts"])
    assert list(facts) == ["Load ID", "POD Score", "Status", "Summary"]
    assert facts["POD Score"] == "87/100"


def test_notify_posts_teams_without_load_id_uses_shipment_custom_id() -> None:
    with patch(
        "app.services.pod_lifecycle.teams_notification_service.post_message_card",
        new_callable=AsyncMock,
    ) as post_mock:
        result = PodLifecycleTeamsNotificationService().notify_from_state(
            _state(
                data={
                    "load_id": "",
                    "shipment_id": "1000324895",
                    "shipment": {"details": {"customId": "30389"}},
                }
            )
        )

    assert result.sent is True
    post_mock.assert_awaited_once()
    assert post_mock.await_args.kwargs["title"] == "POD analyzed — Load 30389"


def test_notify_shadow_still_posts_teams() -> None:
    with patch(
        "app.services.pod_lifecycle.teams_notification_service.post_message_card",
        new_callable=AsyncMock,
    ) as post_mock:
        result = PodLifecycleTeamsNotificationService().notify_from_state(
            _state(data={"workflow_shadow_mode": True})
        )

    assert result.sent is True
    post_mock.assert_awaited_once()


def test_notify_returns_error_when_teams_fails() -> None:
    from app.integrations.teams.webhook import TeamsWebhookError

    with patch(
        "app.services.pod_lifecycle.teams_notification_service.post_message_card",
        new_callable=AsyncMock,
        side_effect=TeamsWebhookError("fail", status_code=500),
    ):
        result = PodLifecycleTeamsNotificationService().notify_from_state(_state())

    assert result.error == "teams_post_failed"
