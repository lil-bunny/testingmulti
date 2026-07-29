"""Load appointment scheduling sheet rows for one customer (gquery or local xlsx)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.integrations.google.sheets import (
    GoogleSheetsError,
    is_google_spreadsheet_url,
    query_public_spreadsheet_by_customer,
)
from app.tools.appointment_scheduling.customer_contact import find_customer_sheet_row
from app.utils.excel import xlsx_bytes_to_sheet_records


def _rows_from_xlsx_bytes(data: bytes) -> list[dict[str, Any]]:
    parsed = xlsx_bytes_to_sheet_records(data)
    rows: list[dict[str, Any]] = []
    for sheet in parsed.get("sheets") or []:
        if isinstance(sheet, dict):
            rows.extend(sheet.get("rows") or [])
    return rows


def load_appointment_customer_rows(
    source: str,
    customer_name: str,
) -> list[dict[str, Any]]:
    """
    Load sheet rows for ``customer_name``.

    - Google Sheets URL: public gviz/tq (gquery) by CUSTOMER column — no XLSX download.
    - Local ``.xlsx`` path: read file and filter (tests / offline only).
    """
    text = str(source or "").strip()
    if not text:
        raise ValueError("appointment_data_source is empty")
    customer = str(customer_name or "").strip()
    if not customer:
        return []

    if text.startswith(("http://", "https://")):
        if not is_google_spreadsheet_url(text):
            raise GoogleSheetsError(
                "appointment_data_source HTTP URL must be a Google Sheets link "
                "(gquery); arbitrary XLSX URLs are not supported"
            )
        return query_public_spreadsheet_by_customer(text, customer)

    data = Path(text).read_bytes()
    all_rows = _rows_from_xlsx_bytes(data)
    row = find_customer_sheet_row(all_rows, customer)
    return [row] if row is not None else []


__all__ = ("load_appointment_customer_rows",)
