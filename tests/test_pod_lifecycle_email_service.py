"""Tests for PodLifecycleEmailService shadow mode."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.pod_lifecycle.email_service import (
    PodLifecycleEmailService,
    PodReminderSendResult,
)
from app.services.workflow_shadow_mail_service import WorkflowShadowMailService


def _state(**data):
    return SimpleNamespace(
        tenant_id="tenant-1",
        execution_id="run-1",
        data={
            "tenant_id": "tenant-1",
            "workflow_lifecycle_id": "wl-1",
            "shipment_id": "ship-1",
            "thread_id": "thread-1",
            "subject": "POD please",
            "body": "Send POD",
            "tenant_settings": {
                "mikey_account_id": "acct-1",
                "pod_lifecycle": {"shadow_mode": True},
            },
            "workflow_shadow_mode": True,
            **data,
        },
    )


def test_send_pod_reminder_shadow_blocks_without_redirect() -> None:
    svc = PodLifecycleEmailService()
    with patch("app.services.pod_lifecycle.email_service.send_email_tool") as send_mock:
        result = svc.send_pod_reminder_from_state(_state())
    assert result.sent is True
    assert result.shadow_skipped is True
    assert result.communication_id is None
    send_mock.assert_not_called()
    patch_data = result.to_state_patch()
    assert patch_data["pod_reminder_sent"] is True
    assert patch_data["pod_reminder_shadow_skipped"] is True


def test_send_pod_reminder_shadow_redirects_without_thread_reply() -> None:
    svc = PodLifecycleEmailService()
    state = _state(
        tenant_settings={
            "mikey_account_id": "acct-1",
            "pod_lifecycle": {
                "shadow_mode": True,
                "shadow_emails": {"to": ["test@freightx.ai"]},
            },
        },
    )
    with patch.object(
        WorkflowShadowMailService,
        "send_redirect_email",
        return_value={"success": True, "communication_id": "comm-pod-shadow-1"},
    ) as redirect_mock:
        with patch("app.services.pod_lifecycle.email_service.send_email_tool") as send_mock:
            result = svc.send_pod_reminder_from_state(state)

    assert result.sent is True
    assert result.shadow_skipped is False
    assert result.communication_id == "comm-pod-shadow-1"
    send_mock.assert_not_called()
    redirect_mock.assert_called_once()
    call_kwargs = redirect_mock.call_args.kwargs
    assert call_kwargs["recipients"].to == ["test@freightx.ai"]
    assert call_kwargs["communication_metadata"]["original_thread_id"] == "thread-1"


def test_send_email_node_delegates_to_service() -> None:
    from app.workflows.nodes import email as email_nodes

    state = _state()
    with patch.object(
        PodLifecycleEmailService,
        "send_pod_reminder_from_state",
        return_value=PodReminderSendResult(sent=True),
    ):
        out = email_nodes.send_email(state)
    assert out.data["pod_reminder_sent"] is True
