"""
Extract tabular rows from persisted ``data_imports.raw_data`` JSON envelopes.

``raw_data`` is shaped by ``DataImportsService`` (``ingest`` + ``mime_type``). For
excel bytes, ``ingest.data.spreadsheet`` mirrors ``app.utils.excel.xlsx_bytes_to_sheet_records``.

Extension points (future):
- CSV or other text tables: add ``iter_*`` helpers and branch on ``ingest.data`` keys.
- Registry by ``data_imports.data_type``: map type → iterator without changing HTTP layer.
- Normalized row schema: wrap yields in a TypedDict or Pydantic model per product.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any


def iter_spreadsheet_rows(raw_data: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """
    Yield one dict per spreadsheet row across all sheets (sheet order preserved).

    Adds ``_sheet_name`` for provenance; strip in clients that only need cell columns.
    Yields nothing when the envelope is missing ``ingest.data.spreadsheet`` or format
    is not ``xlsx``.
    """
    try:
        ingest = raw_data["ingest"]
        data = ingest["data"]
        spreadsheet = data["spreadsheet"]
    except (KeyError, TypeError):
        return
    if not isinstance(spreadsheet, dict):
        return
    if spreadsheet.get("format") != "xlsx":
        return
    sheets = spreadsheet.get("sheets")
    if not isinstance(sheets, list):
        return
    for sheet in sheets:
        if not isinstance(sheet, dict):
            continue
        name = sheet.get("name")
        rows = sheet.get("rows")
        if not isinstance(rows, list):
            continue
        sheet_label = str(name) if name is not None else ""
        for r in rows:
            if not isinstance(r, dict):
                continue
            yield {**r, "_sheet_name": sheet_label}
