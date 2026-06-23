"""Tests for reply_to_thread automatic-reply anchor selection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.unipile_service import UnipileException
from app.tools.email import _select_reply_anchor_email, reply_to_thread
from tests.fixtures.outlook_auto_reply_emails import (
    EMAIL_ID_OOO_CHRIS,
    EMAIL_ID_REMINDER_1,
    load_outlook_auto_reply_thread_fixture,
    outlook_auto_reply_thread_items,
    thread_before_second_reminder,
)


@pytest.fixture(scope="module")
def auto_reply_thread_items() -> list[dict]:
    return outlook_auto_reply_thread_items()


@pytest.fixture(scope="module")
def thread_fixture() -> dict:
    return load_outlook_auto_reply_thread_fixture()


def test_select_anchor_skips_outlook_ooo(auto_reply_thread_items: list[dict]) -> None:
    thread = thread_before_second_reminder(auto_reply_thread_items)
    anchor, skipped = _select_reply_anchor_email(thread, handle_auto_reply=True)
    assert skipped == 1
    assert anchor["id"] == EMAIL_ID_REMINDER_1


def test_select_anchor_without_auto_reply_uses_newest(
    auto_reply_thread_items: list[dict],
) -> None:
    thread = thread_before_second_reminder(auto_reply_thread_items)
    anchor, skipped = _select_reply_anchor_email(thread, handle_auto_reply=False)
    assert skipped == 0
    assert anchor["id"] == EMAIL_ID_OOO_CHRIS


def test_select_anchor_only_automatic_replies_raises() -> None:
    ooo = {
        "type": "OUTLOOK",
        "subject": "Automatic reply: TEST",
        "date": "2026-06-19T19:08:58.000Z",
    }
    with pytest.raises(UnipileException, match="only automatic replies"):
        _select_reply_anchor_email([ooo], handle_auto_reply=True)


@patch("app.tools.email.Unipile")
@patch("app.tools.email._record_outbound_communication", return_value=None)
def test_reply_to_thread_skips_ooo_for_recipients(
    _record_comm: MagicMock,
    unipile_cls: MagicMock,
    auto_reply_thread_items: list[dict],
    thread_fixture: dict,
) -> None:
    thread = thread_before_second_reminder(auto_reply_thread_items)
    unipile = unipile_cls.return_value
    unipile.get_account_email.return_value = thread_fixture["agent_email"]
    unipile.list_emails.return_value = {"items": thread}
    unipile.send_email.return_value = {"success": True, "message_id": "out-1"}

    result = reply_to_thread(
        thread_id=thread_fixture["thread_id"],
        body="<p>Following up</p>",
        account_id=thread_fixture["account_id"],
        handle_auto_reply=True,
    )

    assert result["success"] is True
    assert result.get("skipped_auto_replies") == 1
    send_kwargs = unipile.send_email.call_args.kwargs
    to_ids = {r["identifier"].lower() for r in send_kwargs["to"]}
    cc_ids = {r["identifier"].lower() for r in (send_kwargs.get("cc") or [])}
    assert "chris.alter@shipper.example.com" not in to_ids
    assert "tonya.jackson@shipper.example.com" in to_ids
    assert "blaine.kitchen@carrier.example.com" in to_ids
    assert "taylor.hudson@shipper.example.com" in cc_ids
    assert "chris.alter@shipper.example.com" in cc_ids
    assert "automatic reply" not in send_kwargs["subject"].lower()
    assert send_kwargs["subject"].endswith(thread_fixture["pickup_subject"])
    assert send_kwargs["reply_to"] == EMAIL_ID_REMINDER_1


@patch("app.tools.email.Unipile")
@patch("app.tools.email._record_outbound_communication", return_value=None)
def test_reply_to_thread_handle_auto_reply_false_uses_ooo_recipients(
    _record_comm: MagicMock,
    unipile_cls: MagicMock,
    auto_reply_thread_items: list[dict],
    thread_fixture: dict,
) -> None:
    thread = thread_before_second_reminder(auto_reply_thread_items)
    unipile = unipile_cls.return_value
    unipile.get_account_email.return_value = thread_fixture["agent_email"]
    unipile.list_emails.return_value = {"items": thread}
    unipile.send_email.return_value = {"success": True, "message_id": "out-2"}

    reply_to_thread(
        thread_id=thread_fixture["thread_id"],
        body="<p>Following up</p>",
        account_id=thread_fixture["account_id"],
        handle_auto_reply=False,
    )

    send_kwargs = unipile.send_email.call_args.kwargs
    to_ids = {r["identifier"].lower() for r in send_kwargs["to"]}
    assert to_ids == {"chris.alter@shipper.example.com"}
