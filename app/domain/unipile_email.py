"""Unipile ``mail_received`` email and attachment shapes shared across services."""

from __future__ import annotations

from typing import Any


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
