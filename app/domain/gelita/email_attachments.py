"""Gelita Unipile email xlsx attachment names and classification."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.domain.unipile_email_attachments import (
    attachment_display_name,
    iter_unipile_xlsx_attachments,
)

DELIVERY_LOCATIONS_FILE_NAME = "delivery_location.xlsx"
DELIVERY_LOCATIONS_SHEET_NAME = "Delivery locations"
LOAD_TENDERING_ATTACHMENT_PREFIX = "customers_orders_"


def is_delivery_locations_attachment(file_name: str | None) -> bool:
    """True when the attachment basename matches ``delivery_location.xlsx`` (case-insensitive)."""
    if not file_name or not str(file_name).strip():
        return False
    return (
        Path(str(file_name).strip()).name.lower()
        == DELIVERY_LOCATIONS_FILE_NAME.lower()
    )


def is_load_tendering_attachment(file_name: str | None) -> bool:
    """True when basename is ``.xlsx`` and stem starts with ``customers_orders_`` (case-insensitive)."""
    if not file_name or not str(file_name).strip():
        return False
    name = Path(str(file_name).strip()).name
    if not name.lower().endswith(".xlsx"):
        return False
    stem = name[: -len(".xlsx")]
    return stem.casefold().startswith(LOAD_TENDERING_ATTACHMENT_PREFIX.casefold())


@dataclass(frozen=True)
class GelitaEmailXlsxAttachments:
    """At most one delivery-locations workbook and one load-tendering workbook per email."""

    delivery_locations_attachment: dict[str, Any] | None = None
    load_tendering_xlsx_attachment: dict[str, Any] | None = None


def classify_gelita_email_xlsx_attachments(
    payload: dict[str, Any],
) -> GelitaEmailXlsxAttachments:
    """
    Classify Gelita xlsx attachments in one scan of ``payload["attachments"]``.

    Returns the first ``delivery_location.xlsx`` and first ``customers_orders_*.xlsx``
    when ``has_attachments`` is true; otherwise both values are ``None``.
    """
    if not payload.get("has_attachments"):
        return GelitaEmailXlsxAttachments()

    delivery_locations_attachment: dict[str, Any] | None = None
    load_tendering_xlsx_attachment: dict[str, Any] | None = None

    for attachment in iter_unipile_xlsx_attachments(payload):
        file_name = attachment_display_name(attachment)
        if (
            delivery_locations_attachment is None
            and is_delivery_locations_attachment(file_name)
        ):
            delivery_locations_attachment = attachment
        if (
            load_tendering_xlsx_attachment is None
            and is_load_tendering_attachment(file_name)
        ):
            load_tendering_xlsx_attachment = attachment
        if (
            delivery_locations_attachment is not None
            and load_tendering_xlsx_attachment is not None
        ):
            break

    return GelitaEmailXlsxAttachments(
        delivery_locations_attachment=delivery_locations_attachment,
        load_tendering_xlsx_attachment=load_tendering_xlsx_attachment,
    )
