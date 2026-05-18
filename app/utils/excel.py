"""Spreadsheet decoding: xlsx bytes to JSON-friendly row dicts."""

from __future__ import annotations

import io
from typing import Any

import pandas as pd


def xlsx_bytes_to_sheet_records(
    data: bytes,
    *,
    max_rows_per_sheet: int = 50_000,
) -> dict[str, Any]:
    """
    Read every sheet from an ``.xlsx`` workbook and return plain row records.

    Cell values may still carry pandas/numpy scalar types; callers should pass the
    result through ``ingest_service`` (or equivalent) JSON sanitization before ``jsonb``.
    """
    if not data:
        raise ValueError("empty xlsx bytes")
    if max_rows_per_sheet < 1:
        raise ValueError("max_rows_per_sheet must be >= 1")

    raw = pd.read_excel(io.BytesIO(data), sheet_name=None, engine="openpyxl")
    if not isinstance(raw, dict):
        sheets_map = {"Sheet1": raw}
    else:
        sheets_map = raw

    sheets_out: list[dict[str, Any]] = []
    for name, frame in sheets_map.items():
        if not isinstance(frame, pd.DataFrame):
            continue
        df = frame.head(max_rows_per_sheet).copy()
        df.columns = pd.Index([str(c) for c in df.columns])
        df = df.where(pd.notna(df), None)
        rows = df.to_dict(orient="records")
        sheets_out.append(
            {
                "name": str(name),
                "row_count": len(rows),
                "rows": rows,
            }
        )

    return {
        "format": "xlsx",
        "sheets": sheets_out,
    }
