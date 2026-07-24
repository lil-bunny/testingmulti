"""Shared Unipile email attachment iteration and display-name helpers."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator


def normalize_attachment_extension(value: Any) -> str:
    return str(value or "").strip().lower().lstrip(".")


def attachment_display_name(attachment: Any) -> str:
    if not isinstance(attachment, dict):
        return ""
    for key in ("name", "filename", "file_name"):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def is_pdf_attachment(attachment: dict[str, Any], file_name: str) -> bool:
    mime = str(attachment.get("mime") or attachment.get("content_type") or "").lower()
    if mime == "application/pdf":
        return True
    return file_name.lower().endswith(".pdf")


def iter_unipile_attachments_with_id(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield attachment dicts that have a non-empty Unipile ``id``."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if attachment.get("id") is None or not str(attachment.get("id")).strip():
            continue
        yield attachment


def iter_unipile_xlsx_attachments(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield xlsx attachments that have a non-empty Unipile ``id``."""
    for attachment in iter_unipile_attachments_with_id(payload):
        if normalize_attachment_extension(attachment.get("extension")) != "xlsx":
            continue
        yield attachment


def iter_unipile_pdf_attachments(payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield pdf attachments that have a non-empty Unipile ``id``."""
    for attachment in iter_unipile_attachments_with_id(payload):
        file_name = attachment_display_name(attachment)
        if not is_pdf_attachment(attachment, file_name):
            continue
        yield attachment


def first_unipile_xlsx_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """First valid xlsx attachment with a Unipile ``id`` (tenant-agnostic fallback)."""
    return next(iter_unipile_xlsx_attachments(payload), None)


def first_unipile_pdf_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """First valid pdf attachment with a Unipile ``id``."""
    return next(iter_unipile_pdf_attachments(payload), None)
