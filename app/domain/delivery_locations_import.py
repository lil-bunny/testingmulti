"""Constants and helpers for delivery_location.xlsx email attachments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

DELIVERY_LOCATIONS_FILE_NAME = "delivery_location.xlsx"
DELIVERY_LOCATIONS_SHEET_NAME = "Delivery locations"


def is_delivery_locations_attachment(file_name: str | None) -> bool:
    """True when the attachment basename matches ``delivery_location.xlsx`` (case-insensitive)."""
    if not file_name or not str(file_name).strip():
        return False
    return Path(str(file_name).strip()).name.lower() == DELIVERY_LOCATIONS_FILE_NAME.lower()


def _normalize_attachment_extension(value: Any) -> str:
    return str(value or "").strip().lower().lstrip(".")


def _attachment_display_name(attachment: dict[str, Any]) -> str:
    for key in ("name", "filename", "file_name"):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def unipile_delivery_locations_attachment(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """First xlsx attachment whose filename is ``delivery_location.xlsx``."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if _normalize_attachment_extension(attachment.get("extension")) != "xlsx":
            continue
        if attachment.get("id") is None or not str(attachment.get("id")).strip():
            continue
        if is_delivery_locations_attachment(_attachment_display_name(attachment)):
            return attachment
    return None


def unipile_first_load_tender_xlsx_attachment(
    payload: dict[str, Any],
) -> dict[str, Any] | None:
    """First xlsx attachment that is not the delivery-locations workbook."""
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return None
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        if _normalize_attachment_extension(attachment.get("extension")) != "xlsx":
            continue
        if attachment.get("id") is None or not str(attachment.get("id")).strip():
            continue
        if is_delivery_locations_attachment(_attachment_display_name(attachment)):
            continue
        return attachment
    return None
