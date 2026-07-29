"""Unipile ``mail_received`` email and attachment shapes shared across services."""

from __future__ import annotations

import re
from typing import Any

from app.domain.tenant_settings.email_recipients import normalize_emails_for_matching

_RECIPIENT_ATTENDEE_KEYS = ("to_attendees", "cc_attendees", "bcc_attendees")
_RE_REPLY_SUBJECT = re.compile(r"^Re:\s", re.IGNORECASE)

# Unipile webhook fields that must not enter LangGraph workflow state.
UNIPILE_WORKFLOW_STATE_OMIT_KEYS = frozenset(
    {
        "body_plain",
        "is_complete",
        "read_date",
        "reply_to_attendees",
    }
)


def omit_unipile_workflow_noise_keys(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy ``payload`` without Unipile fields unused by any workflow node."""
    return {
        key: value
        for key, value in payload.items()
        if key not in UNIPILE_WORKFLOW_STATE_OMIT_KEYS
    }


def _has_in_reply_to_value(val: Any) -> bool:
    if val is None:
        return False
    if isinstance(val, dict):
        for key in ("message_id", "id"):
            text = val.get(key)
            if text is not None and str(text).strip():
                return True
        return False
    return bool(str(val).strip())


def is_unipile_email_reply(payload: dict[str, Any]) -> bool:
    """True when Unipile payload looks like a thread reply (official ``in_reply_to`` or Re: fallback)."""
    if _has_in_reply_to_value(payload.get("in_reply_to")):
        return True
    thread_id = payload.get("thread_id")
    if thread_id is None or not str(thread_id).strip():
        return False
    subject = str(payload.get("subject") or "").strip()
    return bool(_RE_REPLY_SUBJECT.match(subject))


def extract_email_id_or_none(payload: dict[str, Any]) -> str | None:
    """Unipile ``email_id`` when present; used for ingress task idempotency at the HTTP edge."""
    raw = payload.get("email_id")
    if raw is None:
        return None
    text = str(raw).strip()
    return text if text else None


def build_unipile_attachment_fetch_context(
    payload: dict[str, Any], attachment: dict[str, Any]
) -> dict[str, str]:
    """IDs needed for Unipile ``get_email_attachment`` / download APIs (webhook has no file URL)."""
    fetch_context: dict[str, str] = {}
    email_id = payload.get("email_id")
    if email_id is not None and str(email_id).strip():
        fetch_context["email_id"] = str(email_id).strip()
    account_id = payload.get("account_id")
    if account_id is not None and str(account_id).strip():
        fetch_context["account_id"] = str(account_id).strip()
    attachment_id = attachment.get("id")
    if attachment_id is not None and str(attachment_id).strip():
        fetch_context["attachment_id"] = str(attachment_id).strip()
    return fetch_context


def extract_email_attachment_metadata(attachment: dict[str, Any]) -> dict[str, Any]:
    """Subset of Unipile attachment object (``id``, ``name``, ``mime``, ``extension``, ``size``)."""
    if not isinstance(attachment, dict):
        return {}
    metadata: dict[str, Any] = {}
    for key in ("id", "name", "mime", "extension", "size"):
        if key not in attachment:
            continue
        value = attachment.get(key)
        if value is None:
            continue
        if key == "size":
            try:
                metadata[key] = int(value)
            except (TypeError, ValueError):
                metadata[key] = value
        else:
            text_value = str(value).strip()
            if text_value:
                metadata[key] = text_value
    return metadata


def _attendee_identifiers(attendees: Any) -> list[str]:
    if not isinstance(attendees, list):
        return []
    out: list[str] = []
    for att in attendees:
        if not isinstance(att, dict):
            continue
        ident = att.get("identifier")
        if ident is not None and str(ident).strip():
            out.append(str(ident))
    return out


def extract_recipient_emails(payload: dict[str, Any]) -> list[str]:
    """
    Union of ``to_attendees``, ``cc_attendees``, and ``bcc_attendees`` identifiers.

    Normalized: strip, lowercase, dedupe; drops blanks and strings without ``@``.
    """
    raw: list[str] = []
    for key in _RECIPIENT_ATTENDEE_KEYS:
        raw.extend(_attendee_identifiers(payload.get(key)))
    return normalize_emails_for_matching(raw, required=False)


def attachments_metadata_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalized attachment list for ``communications.metadata`` (entries require ``id``)."""
    raw = payload.get("attachments")
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        meta = extract_email_attachment_metadata(item)
        if meta.get("id"):
            out.append(meta)
    return out
