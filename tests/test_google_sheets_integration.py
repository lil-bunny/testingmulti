"""Google Sheets integration tests."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.integrations.google.sheets import (
    GoogleSheetsError,
    build_public_xlsx_export_url,
    fetch_public_spreadsheet_xlsx,
    parse_spreadsheet_url,
)


def test_parse_spreadsheet_url_from_edit_link():
    sheet_id, gid = parse_spreadsheet_url(
        "https://docs.google.com/spreadsheets/d/1PqAPAFxGYNSiHUYzLtCNh-ezvpGPpq4W1C8D0PjComk/edit?usp=sharing"
    )
    assert sheet_id == "1PqAPAFxGYNSiHUYzLtCNh-ezvpGPpq4W1C8D0PjComk"
    assert gid is None


def test_parse_spreadsheet_url_with_gid():
    sheet_id, gid = parse_spreadsheet_url(
        "https://docs.google.com/spreadsheets/d/abc123/edit#gid=456789"
    )
    assert sheet_id == "abc123"
    assert gid == "456789"


def test_build_public_xlsx_export_url():
    url = build_public_xlsx_export_url("abc123", "99")
    assert url == "https://docs.google.com/spreadsheets/d/abc123/export?format=xlsx&gid=99"


def test_fetch_public_spreadsheet_xlsx():
    fake_bytes = b"PK\x03\x04fake-xlsx"
    with patch("app.integrations.google.sheets.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.content = fake_bytes
        data = fetch_public_spreadsheet_xlsx(
            "https://docs.google.com/spreadsheets/d/abc123/edit"
        )
    assert data == fake_bytes
    mock_get.assert_called_once()
    assert mock_get.call_args.args[0].endswith("/abc123/export?format=xlsx")


def test_fetch_public_spreadsheet_xlsx_http_error():
    with patch("app.integrations.google.sheets.httpx.get") as mock_get:
        mock_get.return_value.status_code = 403
        mock_get.return_value.text = "Forbidden"
        with pytest.raises(GoogleSheetsError):
            fetch_public_spreadsheet_xlsx(
                "https://docs.google.com/spreadsheets/d/abc123/edit"
            )
