"""Appointment scheduling sheet loader tests."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from app.integrations.google.sheets import GoogleSheetsError
from app.services.appointment_scheduling.sheet_loader import load_appointment_customer_rows


def test_load_appointment_customer_rows_from_google_gquery():
    url = "https://docs.google.com/spreadsheets/d/abc123/edit#gid=1"
    with patch(
        "app.services.appointment_scheduling.sheet_loader.query_public_spreadsheet_by_customer",
        return_value=[
            {
                "CUSTOMER": "Acme",
                "APPOINTMENT MODE": "email",
                "CONTACT DETAILS(EMAILS)": "a@example.com",
            }
        ],
    ) as mock_query:
        rows = load_appointment_customer_rows(url, "Acme")

    assert len(rows) == 1
    assert rows[0]["CUSTOMER"] == "Acme"
    mock_query.assert_called_once_with(url, "Acme")


def test_load_appointment_customer_rows_rejects_non_google_http():
    with pytest.raises(GoogleSheetsError):
        load_appointment_customer_rows(
            "https://example.com/sheet.xlsx",
            "Acme",
        )


def test_load_appointment_customer_rows_from_local_path(tmp_path):
    path = tmp_path / "sheet.xlsx"
    pd.DataFrame(
        [
            {
                "CUSTOMER": "Local Co",
                "APPOINTMENT MODE": "email",
                "CONTACT DETAILS": "local@example.com",
            },
            {
                "CUSTOMER": "Other",
                "APPOINTMENT MODE": "email",
                "CONTACT DETAILS": "other@example.com",
            },
        ]
    ).to_excel(path, index=False)
    rows = load_appointment_customer_rows(str(path), "Local Co")
    assert len(rows) == 1
    assert rows[0]["CUSTOMER"] == "Local Co"
