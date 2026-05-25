"""Tests for ``app.utils.excel``."""

from __future__ import annotations

from io import BytesIO

import pandas as pd


def test_xlsx_bytes_multi_sheet_named_rows() -> None:
    from app.utils.excel import xlsx_bytes_to_sheet_records

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        pd.DataFrame({"ColA": [1, 2], "ColB": ["x", "y"]}).to_excel(
            writer, sheet_name="First", index=False
        )
        pd.DataFrame({1: [10], 2: [20]}).to_excel(
            writer, sheet_name="Second", index=False
        )
    raw = buf.getvalue()
    out = xlsx_bytes_to_sheet_records(raw, max_rows_per_sheet=10_000)
    assert out["format"] == "xlsx"
    assert len(out["sheets"]) == 2
    assert out["sheets"][0]["name"] == "First"
    assert out["sheets"][0]["row_count"] == 2
    assert out["sheets"][0]["rows"][0]["ColA"] == 1
    assert out["sheets"][1]["rows"][0]["1"] == 10


def test_xlsx_max_rows_per_sheet_head() -> None:
    from app.utils.excel import xlsx_bytes_to_sheet_records

    buf = BytesIO()
    pd.DataFrame({"n": list(range(5))}).to_excel(buf, index=False, engine="openpyxl")
    out = xlsx_bytes_to_sheet_records(buf.getvalue(), max_rows_per_sheet=3)
    assert out["sheets"][0]["row_count"] == 3


def test_xlsx_empty_bytes_raises() -> None:
    from app.utils.excel import xlsx_bytes_to_sheet_records

    try:
        xlsx_bytes_to_sheet_records(b"")
    except ValueError as e:
        assert "empty" in str(e).lower()
        return
    raise AssertionError("expected ValueError")

