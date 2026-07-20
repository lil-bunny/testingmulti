"""Load appointment scheduling spreadsheet rows (local path or Google Sheets URL)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from app.integrations.google.sheets import GoogleSheetsError, fetch_public_spreadsheet_xlsx, is_google_spreadsheet_url
from app.utils.excel import xlsx_bytes_to_sheet_records


def _rows_from_xlsx_bytes(data: bytes) -> list[dict[str, Any]]:
    parsed = xlsx_bytes_to_sheet_records(data)
    rows: list[dict[str, Any]] = []
    for sheet in parsed.get("sheets") or []:
        if isinstance(sheet, dict):
            rows.extend(sheet.get("rows") or [])
    return rows


def load_appointment_sheet_rows(source: str) -> list[dict[str, Any]]:
    """
    Load row dicts from ``appointment_data_source``.

    Supports:
    - local ``.xlsx`` path
    - public Google Sheets share/edit URL (exported as xlsx)
    - other ``http(s)`` URLs pointing at ``.xlsx`` bytes
    """
    text = str(source or "").strip()
    if not text:
        raise ValueError("appointment_data_source is empty")

    if text.startswith(("http://", "https://")):
        if is_google_spreadsheet_url(text):
            data = fetch_public_spreadsheet_xlsx(text)
        else:
            try:
                response = httpx.get(text, timeout=30.0, follow_redirects=True)
            except httpx.HTTPError as exc:
                raise GoogleSheetsError(f"Spreadsheet URL download failed: {exc}") from exc
            if response.status_code >= 400:
                raise GoogleSheetsError(
                    "Spreadsheet URL download failed",
                    status_code=response.status_code,
                )
            data = response.content
    else:
        data = Path(text).read_bytes()

    return _rows_from_xlsx_bytes(data)
