"""Tests for AppointmentSchedulingEmailService."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from app.services.appointment_scheduling.email_service import AppointmentSchedulingEmailService


def _state(**overrides):
    data = {
        "workflow_lifecycle_id": "11111111-2222-3333-4444-555555555555",
        "tenant_id": "00000000-0000-4000-8000-0000000000e1",
        "tenant_settings": {"mikey_account_id": "acc-1"},
        "workflow_lifecycle_metadata": {
            "email_draft": {
                "to": "wh@example.com",
                "cc": ["cc@example.com"],
                "subject": "DEL APPT REQ",
                "full_html": "<p>Hello</p>",
            }
        },
    }
    data.update(overrides)
    return SimpleNamespace(tenant_id=data["tenant_id"], execution_id="run-1", data=data)


@patch("app.services.appointment_scheduling.email_service.Unipile")
def test_send_from_state_records_communication_and_transitions_sub_status(
    mock_unipile_cls: MagicMock,
) -> None:
    mock_unipile_cls.return_value.send_email.return_value = {
        "success": True,
        "tracking_id": "trk-1",
    }
    communications = MagicMock()
    communications.record_outbound_from_send.return_value = "comm-1"
    activity = MagicMock()
    svc = AppointmentSchedulingEmailService(
        communications_service=communications,
        activity_service=activity,
    )

    result = svc.send_from_state(_state())

    assert result.sent is True
    assert result.communication_id == "comm-1"
    communications.record_outbound_from_send.assert_called_once()
    activity.record_confirm_email_sent.assert_called_once()
    activity.record_awaiting_customer_reply.assert_called_once()
    extra = communications.record_outbound_from_send.call_args.kwargs["extra_metadata"]
    assert extra["source"] == "appointment_draft_send"


def test_send_from_state_missing_draft() -> None:
    state = _state(workflow_lifecycle_metadata={"email_draft": {"to": "a@b.com"}})
    result = AppointmentSchedulingEmailService().send_from_state(state)
    assert result.sent is False
    assert result.error == "missing_email_draft"
