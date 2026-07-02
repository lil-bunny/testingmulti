"""Tests for Unipile reply detection helpers."""

from __future__ import annotations

from app.domain.unipile_email import is_unipile_email_reply


def test_is_unipile_email_reply_object_in_reply_to() -> None:
    assert is_unipile_email_reply(
        {
            "in_reply_to": {
                "message_id": "<parent@example.com>",
                "id": "mail-parent-1",
            },
            "thread_id": "thread-1",
        }
    )


def test_is_unipile_email_reply_string_in_reply_to() -> None:
    assert is_unipile_email_reply(
        {"in_reply_to": "parent-msg", "thread_id": "thread-1"}
    )


def test_is_unipile_email_reply_re_subject_fallback() -> None:
    assert is_unipile_email_reply(
        {
            "thread_id": "thread-1",
            "subject": "Re: Rate confirmation for shipment: #30389",
        }
    )


def test_is_unipile_email_reply_rejects_plain_new_email() -> None:
    assert not is_unipile_email_reply(
        {
            "thread_id": "thread-1",
            "subject": "Rate confirmation for shipment: #30389",
            "body": "Driver John",
        }
    )


def test_is_unipile_email_reply_rejects_empty_in_reply_to_object() -> None:
    assert not is_unipile_email_reply(
        {"in_reply_to": {}, "thread_id": "thread-1", "subject": "Hello"}
    )
