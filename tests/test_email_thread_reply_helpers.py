"""Tests for email thread reply pure helpers."""

from __future__ import annotations

from app.domain.email_thread_reply import exclude_emails_for_reply


def test_exclude_emails_for_reply_uses_alias_when_set() -> None:
    assert exclude_emails_for_reply(
        primary_email="primary@example.com",
        from_email="alias@example.com",
    ) == "alias@example.com"


def test_exclude_emails_for_reply_falls_back_to_primary() -> None:
    assert exclude_emails_for_reply(
        primary_email="primary@example.com",
        from_email=None,
    ) == "primary@example.com"
