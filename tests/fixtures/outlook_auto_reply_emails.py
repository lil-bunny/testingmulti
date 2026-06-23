"""Sample Unipile Outlook thread with an automatic reply (OOO) for email tool tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_FIXTURE_PATH = Path(__file__).resolve().parent / "outlook_auto_reply_thread.json"

EMAIL_ID_REMINDER_1 = "email-reminder-1"
EMAIL_ID_OOO_CHRIS = "email-ooo-chris"
EMAIL_ID_CARRIER_REPLY = "email-carrier-reply"


def load_outlook_auto_reply_thread_fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def outlook_auto_reply_thread_items() -> list[dict[str, Any]]:
    return list(load_outlook_auto_reply_thread_fixture()["items"])


def thread_before_second_reminder(items: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Newest is Chris OOO; reminder 1 is the anchor when auto-replies are skipped."""
    source = items if items is not None else outlook_auto_reply_thread_items()
    allowed = {EMAIL_ID_OOO_CHRIS, EMAIL_ID_REMINDER_1}
    return [item for item in source if item.get("id") in allowed]


def ack_received_ooo_webhook_payload(
    *,
    thread_id: str | None = None,
    lifecycle_id: str | None = None,
    tender_id: str | None = None,
    communication_id: str | None = None,
) -> dict[str, Any]:
    """Unipile ``mail_received`` shape for an Outlook OOO on a linked carrier thread."""
    fixture = load_outlook_auto_reply_thread_fixture()
    ooo = next(
        item for item in fixture["items"] if item["id"] == EMAIL_ID_OOO_CHRIS
    )
    payload = {
        "event": "mail_received",
        "email_id": ooo["id"],
        "subject": ooo["subject"],
        "from_attendee": ooo.get("from_attendee"),
        "to_attendees": ooo.get("to_attendees"),
        "cc_attendees": ooo.get("cc_attendees"),
        "bcc_attendees": ooo.get("bcc_attendees"),
        "account_id": fixture.get("account_id"),
        "in_reply_to": {"message_id": "<parent-reminder@example.com>"},
    }
    if thread_id is not None:
        payload["thread_id"] = thread_id
    if lifecycle_id is not None:
        payload["workflow_lifecycle_id"] = lifecycle_id
    if tender_id is not None:
        payload["tender_id"] = tender_id
    if communication_id is not None:
        payload["communication_id"] = communication_id
    return payload
