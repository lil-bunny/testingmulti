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


def parse_unipile_webhook_name(webhook_name: str) -> tuple[str, str] | None:
    """Return ``(base_name, env_suffix)`` from ``{base}_{env}`` or ``None`` if malformed."""
    raw = (webhook_name or "").strip()
    if "_" not in raw:
        return None
    base, env = raw.rsplit("_", 1)
    base, env = base.strip(), env.strip()
    if not base or not env:
        return None
    return base, env


def resolve_unipile_webhook_base_name(webhook_name: str, expected_env: str) -> str | None:
    """Base ``email_webhook_name`` when suffix matches deployment ``ENV``, else ``None``."""
    parsed = parse_unipile_webhook_name(webhook_name)
    if not parsed:
        return None
    base, env = parsed
    if env.lower() != (expected_env or "").strip().lower():
        return None
    return base


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
