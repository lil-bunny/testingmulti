"""Appointment scheduling sheet loader tests."""

from __future__ import annotations

from io import BytesIO
from unittest.mock import patch

import pandas as pd

from app.services.appointment_scheduling.sheet_loader import load_appointment_sheet_rows


def test_load_appointment_sheet_rows_from_google_url(tmp_path):
    buffer = BytesIO()
    pd.DataFrame([{"CUSTOMER": "Acme", "CONTACT DETAILS": "a@example.com"}]).to_excel(
        buffer, index=False
    )
    fake_xlsx = buffer.getvalue()

    url = "https://docs.google.com/spreadsheets/d/abc123/edit?usp=sharing"
    with patch(
        "app.services.appointment_scheduling.sheet_loader.fetch_public_spreadsheet_xlsx",
        return_value=fake_xlsx,
    ):
        rows = load_appointment_sheet_rows(url)

    assert len(rows) == 1
    assert rows[0]["CUSTOMER"] == "Acme"


def test_load_appointment_sheet_rows_from_local_path(tmp_path):
    path = tmp_path / "sheet.xlsx"
    pd.DataFrame([{"CUSTOMER": "Local Co", "CONTACT DETAILS": "local@example.com"}]).to_excel(
        path, index=False
    )
    rows = load_appointment_sheet_rows(str(path))
    assert rows[0]["CUSTOMER"] == "Local Co"
