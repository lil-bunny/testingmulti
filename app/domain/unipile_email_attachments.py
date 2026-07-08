"""Shared Unipile email attachment iteration for xlsx ingest."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def normalize_attachment_extension(value: Any) -> str:
    return str(value or "").strip().lower().lstrip(".")


def attachment_display_name(attachment: dict[str, Any]) -> str:
    for key in ("name", "filename", "file_name"):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def iter_unipile_xlsx_attachments(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield xlsx attachments that have a non-empty Unipile ``id``."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if normalize_attachment_extension(attachment.get("extension")) != "xlsx":
            continue
        if attachment.get("id") is None or not str(attachment.get("id")).strip():
            continue
        yield attachment


def first_unipile_xlsx_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """First valid xlsx attachment with a Unipile ``id`` (tenant-agnostic fallback)."""
    return next(iter_unipile_xlsx_attachments(payload), None)
