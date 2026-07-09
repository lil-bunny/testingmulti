"""T3RA Unipile email ratecon PDF attachment names and selection."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.domain.unipile_email_attachments import (
    attachment_display_name,
    is_pdf_attachment,
    iter_unipile_pdf_attachments,
)

CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET = "carrier_rate_confirmation"


def load_id_from_ratecon_attachment_name(file_name: str) -> str | None:
    """Last contiguous digit run from basename stem (matches ratecon classifier)."""
    stem = Path(file_name).stem
    digit_runs = re.findall(r"\d+", stem)
    if not digit_runs:
        return None
    return digit_runs[-1]


def unipile_ratecon_pdf_attachment(payload: dict[str, Any]) -> dict[str, Any] | None:
    """
    First PDF attachment whose filename contains ``carrier_rate_confirmation``.

    Same selection rules as ``extract_ratecon_metadata_from_payload``.
    """
    for attachment in iter_unipile_pdf_attachments(payload):
        file_name = attachment_display_name(attachment)
        if not file_name:
            continue
        if CARRIER_RATE_CONFIRMATION_FILENAME_SNIPPET not in file_name.lower():
            continue
        if not is_pdf_attachment(attachment, file_name):
            continue
        return attachment
    return None
