"""Tests for WorkflowShadowMailService shadow redirect sends."""

from __future__ import annotations

from unittest.mock import patch

from app.domain.tenant_settings.email_recipients import EmailRecipients
from app.services.workflow_shadow_mail_service import WorkflowShadowMailService


def test_send_redirect_email_prefixes_subject_and_omits_thread_id() -> None:
    recipients = EmailRecipients(to=["test@freightx.ai"], cc=["cc@freightx.ai"])
    with patch("app.services.workflow_shadow_mail_service.send_email_tool") as send_mock:
        send_mock.return_value = {"success": True, "communication_id": "comm-1"}
        result = WorkflowShadowMailService().send_redirect_email(
            tenant_id="tenant-1",
            recipients=recipients,
            subject="Driver reminder",
            body="Please send driver info",
            account_id="acct-1",
            workflow_run_id="run-1",
            communication_metadata={"source": "driver_assignment_reminder"},
        )

    assert result == {"success": True, "communication_id": "comm-1"}
    send_mock.assert_called_once()
    call_args = send_mock.call_args
    assert call_args.args[0] == ["test@freightx.ai"]
    call_kwargs = call_args.kwargs
    assert call_kwargs["thread_id"] is None
    assert call_kwargs["subject"] == "[SHADOW] Driver reminder"
    assert call_kwargs["cc"] == ["cc@freightx.ai"]
    assert call_kwargs["communication_metadata"]["shadow_mail_redirect"] is True
    assert call_kwargs["communication_metadata"]["shadow_mail_to"] == ["test@freightx.ai"]
    assert call_kwargs["communication_metadata"]["source"] == "driver_assignment_reminder"


def test_send_redirect_email_includes_load_id_in_subject() -> None:
    recipients = EmailRecipients(to=["test@freightx.ai"])
    with patch("app.services.workflow_shadow_mail_service.send_email_tool") as send_mock:
        send_mock.return_value = {"success": True}
        WorkflowShadowMailService().send_redirect_email(
            tenant_id="tenant-1",
            recipients=recipients,
            subject="Driver reminder",
            body="body",
            account_id="acct-1",
            load_id="62369",
        )
    assert send_mock.call_args.kwargs["subject"] == "[SHADOW] 62369 Driver reminder"


def test_send_redirect_email_load_id_from_metadata() -> None:
    recipients = EmailRecipients(to=["test@freightx.ai"])
    with patch("app.services.workflow_shadow_mail_service.send_email_tool") as send_mock:
        send_mock.return_value = {"success": True}
        WorkflowShadowMailService().send_redirect_email(
            tenant_id="tenant-1",
            recipients=recipients,
            subject="POD Request",
            body="body",
            account_id="acct-1",
            communication_metadata={"load_id": "61913"},
        )
    assert send_mock.call_args.kwargs["subject"] == "[SHADOW] 61913 POD Request"
