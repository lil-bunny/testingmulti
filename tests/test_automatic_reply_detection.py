"""Unit tests for Outlook automatic reply detection."""

from __future__ import annotations

import pytest

from app.utils.automatic_reply_detection import (
    is_automatic_reply_email,
    is_outlook_automatic_reply,
    strip_automatic_reply_subject_prefix,
)
from tests.fixtures.outlook_auto_reply_emails import (
    EMAIL_ID_OOO_CHRIS,
    EMAIL_ID_REMINDER_1,
    outlook_auto_reply_thread_items,
)


@pytest.fixture(scope="module")
def auto_reply_thread_items() -> list[dict]:
    return outlook_auto_reply_thread_items()


def test_outlook_automatic_reply_detects_chris_ooo(auto_reply_thread_items: list[dict]) -> None:
    chris_ooo = next(item for item in auto_reply_thread_items if item["id"] == EMAIL_ID_OOO_CHRIS)
    assert is_outlook_automatic_reply(chris_ooo) is True
    assert is_automatic_reply_email(chris_ooo) is True


def test_outlook_automatic_reply_re_prefix(auto_reply_thread_items: list[dict]) -> None:
    chris_ooo = next(item for item in auto_reply_thread_items if item["id"] == EMAIL_ID_OOO_CHRIS)
    re_wrapped = {**chris_ooo, "subject": "Re: Automatic reply: PICK UP REQUEST # 97061"}
    assert is_outlook_automatic_reply(re_wrapped) is True


def test_real_replies_not_automatic(auto_reply_thread_items: list[dict]) -> None:
    reminder_one = next(item for item in auto_reply_thread_items if item["id"] == EMAIL_ID_REMINDER_1)
    assert is_outlook_automatic_reply(reminder_one) is False
    assert is_automatic_reply_email(reminder_one) is False


def test_gmail_same_subject_not_automatic() -> None:
    email = {
        "type": "GMAIL",
        "subject": "Automatic reply: PICK UP REQUEST # 97061",
    }
    assert is_automatic_reply_email(email) is False


def test_webhook_payload_without_type_detects_outlook_ooo() -> None:
    email = {
        "event": "mail_received",
        "subject": "Automatic reply: Fw: PICK UP REQUEST # 97088 PO# 169-00",
        "from_attendee": {"identifier": "ana.gelita.test@freightx.ai"},
    }
    assert is_automatic_reply_email(email) is True


def test_strip_automatic_reply_subject_prefix() -> None:
    subject = "Re: Automatic reply: PICK UP REQUEST # 97061 _ PO# 26111855 OP _ JUNE 22"
    assert (
        strip_automatic_reply_subject_prefix(subject)
        == "PICK UP REQUEST # 97061 _ PO# 26111855 OP _ JUNE 22"
    )


def test_strip_automatic_reply_subject_prefix_plain() -> None:
    subject = "Automatic reply: PICK UP REQUEST # 97061"
    assert strip_automatic_reply_subject_prefix(subject) == "PICK UP REQUEST # 97061"
