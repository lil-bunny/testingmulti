"""Ratecon email attachment selection (Unipile ``mail_received`` payloads)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET = "carrier_rate_confirmation"


def attachment_display_filename(attachment: Any) -> str:
    if not isinstance(attachment, dict):
        return ""
    for key in ("name", "filename", "file_name"):
        value = attachment.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def is_pdf_attachment(attachment: dict[str, Any], filename: str) -> bool:
    mime = str(attachment.get("mime") or attachment.get("content_type") or "").lower()
    if mime == "application/pdf":
        return True
    return filename.lower().endswith(".pdf")


def load_id_from_ratecon_attachment_name(filename: str) -> str | None:
    """Last contiguous digit run from basename stem (matches ratecon classifier)."""
    stem = Path(filename).stem
    runs = re.findall(r"\d+", stem)
    if not runs:
        return None
    return runs[-1]


def unipile_ratecon_pdf_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    First PDF attachment whose filename contains ``carrier_rate_confirmation``.

    Same selection rules as ``extract_ratecon_metadata_from_payload``.
    """
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return None

    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        attachment_name = attachment_display_filename(attachment)
        if not attachment_name:
            continue
        if CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET not in attachment_name.lower():
            continue
        if not is_pdf_attachment(attachment, attachment_name):
            continue
        return attachment
    return None
