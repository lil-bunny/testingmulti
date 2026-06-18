"""CommunicationsService.send_thread_reply unit tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.communications.service import CommunicationsService
from app.services.unipile_service import UnipileException


@patch("app.services.communications.service.Unipile")
def test_send_thread_reply_records_outbound_and_returns_communication_id(
    mock_unipile_cls: MagicMock,
) -> None:
    mock_unipile = mock_unipile_cls.return_value
    mock_unipile.get_account_email.return_value = "mikey@example.com"
    mock_unipile.list_emails.return_value = {
        "items": [
            {
                "id": "msg-1",
                "role": "received",
                "subject": "Rate confirmation",
                "date": "2026-06-17T12:00:00Z",
                "from_attendee": {"identifier": "carrier@example.com"},
                "to_attendees": [{"identifier": "mikey@example.com"}],
                "cc_attendees": [],
            }
        ]
    }
    mock_unipile.send_email.return_value = {"success": True, "id": "ext-1"}

    svc = CommunicationsService(repository=MagicMock())
    svc.record_outbound_from_send = MagicMock(return_value="comm-uuid-1")  # type: ignore[method-assign]

    result = svc.send_thread_reply(
        tenant_id="tenant-uuid-1",
        thread_id="thread-1",
        body="Please send driver info",
        account_id="acct-1",
        subject=None,
        workflow_run_id="run-1",
        communication_metadata={"source": "driver_assignment_reminder"},
    )

    assert result["success"] is True
    assert result["communication_id"] == "comm-uuid-1"
    svc.record_outbound_from_send.assert_called_once()
    mock_unipile.send_email.assert_called_once()


def test_send_thread_reply_requires_thread_id() -> None:
    svc = CommunicationsService(repository=MagicMock())
    with pytest.raises(UnipileException, match="thread_id"):
        svc.send_thread_reply(
            tenant_id="tenant-uuid-1",
            thread_id="",
            body="body",
            account_id="acct-1",
        )
