"""Constants and helpers for Gelita load-tender email attachments (``customers_orders_*.xlsx``)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.delivery_locations_import import (
    _attachment_display_name,
    _normalize_attachment_extension,
)

LOAD_TENDERING_ATTACHMENT_PREFIX = "customers_orders_"


def is_load_tendering_attachment(file_name: str | None) -> bool:
    """True when basename is ``.xlsx`` and stem starts with ``customers_orders_`` (case-insensitive)."""
    if not file_name or not str(file_name).strip():
        return False
    name = Path(str(file_name).strip()).name
    if not name.lower().endswith(".xlsx"):
        return False
    stem = name[: -len(".xlsx")]
    return stem.casefold().startswith(LOAD_TENDERING_ATTACHMENT_PREFIX.casefold())


def email_load_tender_xlsx_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """First xlsx email attachment whose filename matches ``customers_orders_`` prefix."""
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
        if is_load_tendering_attachment(_attachment_display_name(attachment)):
            return attachment
    return None
