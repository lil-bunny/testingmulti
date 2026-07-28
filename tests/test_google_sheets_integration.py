"""Google Sheets integration tests (gviz/tq gquery)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.integrations.google.sheets import (
    GoogleSheetsError,
    build_customer_gviz_query,
    escape_gviz_string,
    parse_gviz_table_response,
    parse_spreadsheet_url,
    query_public_spreadsheet_by_customer,
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


def test_escape_gviz_string_doubles_quotes():
    assert escape_gviz_string("O'Brien DC") == "O''Brien DC"


def test_build_customer_gviz_query_lowercases():
    assert build_customer_gviz_query("Acme Corp") == (
        "select * where lower(C) = 'acme corp'"
    )


def test_parse_gviz_table_response():
    body = (
        "/*O_o*/\ngoogle.visualization.Query.setResponse("
        '{"table":{"cols":[{"label":"CUSTOMER"},{"label":"CONTACT DETAILS(EMAILS)"}],'
        '"rows":[{"c":[{"v":"Acme Corp"},{"v":"ops@acme.example"}]}]}}'
        ");"
    )
    rows = parse_gviz_table_response(body)
    assert rows == [
        {"CUSTOMER": "Acme Corp", "CONTACT DETAILS(EMAILS)": "ops@acme.example"}
    ]


def test_parse_gviz_table_response_invalid():
    with pytest.raises(GoogleSheetsError):
        parse_gviz_table_response("not-json")


def test_query_public_spreadsheet_by_customer():
    gviz_body = (
        '{"table":{"cols":[{"label":"CUSTOMER"},{"label":"CONTACT DETAILS(EMAILS)"}],'
        '"rows":[{"c":[{"v":"PETCO DC 810"},{"v":"wh@example.com"}]}]}}'
    )
    with patch("app.integrations.google.sheets.httpx.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = gviz_body
        rows = query_public_spreadsheet_by_customer(
            "https://docs.google.com/spreadsheets/d/abc123/edit#gid=0",
            "PETCO DC 810",
        )
    assert len(rows) == 1
    assert rows[0]["CUSTOMER"] == "PETCO DC 810"
    request_url = mock_get.call_args.args[0]
    assert "/abc123/gviz/tq?" in request_url
    assert "gid=0" in request_url
    assert "tq=" in request_url


def test_query_public_spreadsheet_by_customer_http_error():
    with patch("app.integrations.google.sheets.httpx.get") as mock_get:
        mock_get.return_value.status_code = 403
        mock_get.return_value.text = "Forbidden"
        with pytest.raises(GoogleSheetsError):
            query_public_spreadsheet_by_customer(
                "https://docs.google.com/spreadsheets/d/abc123/edit",
                "Acme",
            )
