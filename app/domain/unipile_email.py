"""Unipile ``mail_received`` email and attachment shapes shared across services."""

from __future__ import annotations

from typing import Any

from app.domain.tenant_settings.email_recipients import normalize_emails_for_matching

_RECIPIENT_ATTENDEE_KEYS = ("to_attendees", "cc_attendees", "bcc_attendees")


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
