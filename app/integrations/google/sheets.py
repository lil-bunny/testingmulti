"""Google Sheets public HTTP helpers (gviz/tq query + URL parse)."""

from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

_DEFAULT_TIMEOUT_S = 30.0
_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


class GoogleSheetsError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def is_google_spreadsheet_url(source: str) -> bool:
    text = str(source or "").strip().lower()
    return text.startswith(("http://", "https://")) and "docs.google.com/spreadsheets" in text


def parse_spreadsheet_url(url: str) -> tuple[str, str | None]:
    """Return ``(sheet_id, gid)`` from a Google Sheets share/edit/export URL."""
    parsed = urlparse(str(url or "").strip())
    match = _SHEET_ID_RE.search(parsed.path)
    if not match:
        raise GoogleSheetsError("Could not parse Google Sheets id from URL")
    sheet_id = match.group(1)

    gid: str | None = None
    values = parse_qs(parsed.query).get("gid")
    if values and values[0]:
        gid = str(values[0]).strip() or None
    if gid is None and parsed.fragment:
        fragment = parse_qs(parsed.fragment.lstrip("#"))
        frag_gid = fragment.get("gid")
        if frag_gid and frag_gid[0]:
            gid = str(frag_gid[0]).strip() or None

    return sheet_id, gid


def escape_gviz_string(value: str) -> str:
    """Escape a string literal for Google Visualization Query Language."""
    return str(value or "").replace("\\", "\\\\").replace("'", "''")


def build_customer_gviz_query(customer_name: str) -> str:
    """Match CUSTOMER column (C) case-insensitively — same sheet layout as AgenticAI."""
    target = escape_gviz_string(str(customer_name or "").strip().lower())
    return f"select * where lower(C) = '{target}'"


def build_gviz_tq_url(sheet_id: str, *, gid: str | None, tq_query: str) -> str:
    params = {
        "tqx": "out:json;responseHandler:none",
        "tq": tq_query,
    }
    if gid:
        params["gid"] = gid
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?"
        f"{urlencode(params, quote_via=quote)}"
    )


def parse_gviz_table_response(text: str) -> list[dict[str, Any]]:
    """Parse gviz JSON (optional JS padding) into header→value row dicts."""
    payload = str(text or "").strip()
    start = payload.find("{")
    end = payload.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise GoogleSheetsError(
            "Unexpected Google Sheets gviz response format",
            body=payload[:500],
        )
    try:
        data = json.loads(payload[start : end + 1])
    except json.JSONDecodeError as exc:
        raise GoogleSheetsError(
            "Google Sheets gviz response was not valid JSON",
            body=payload[:500],
        ) from exc

    table = data.get("table") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        raise GoogleSheetsError("Google Sheets gviz response missing table")

    cols_raw = table.get("cols") or []
    labels: list[str] = []
    for col in cols_raw:
        if not isinstance(col, dict):
            labels.append("")
            continue
        label = str(col.get("label") or col.get("id") or "").strip()
        labels.append(label)

    rows: list[dict[str, Any]] = []
    for raw_row in table.get("rows") or []:
        if not isinstance(raw_row, dict):
            continue
        cells = raw_row.get("c") or []
        row_dict: dict[str, Any] = {}
        for label, cell in zip(labels, cells, strict=False):
            if not label:
                continue
            if cell is None:
                row_dict[label] = None
            elif isinstance(cell, dict):
                row_dict[label] = cell.get("v")
            else:
                row_dict[label] = cell
        if row_dict:
            rows.append(row_dict)
    return rows


def query_public_spreadsheet_rows(
    url: str,
    *,
    tq_query: str,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Run a public Google Sheets gviz/tq query; return matching row dicts."""
    sheet_id, gid = parse_spreadsheet_url(url)
    query = str(tq_query or "").strip()
    if not query:
        raise GoogleSheetsError("gviz tq query is empty")
    request_url = build_gviz_tq_url(sheet_id, gid=gid, tq_query=query)
    try:
        response = httpx.get(request_url, timeout=timeout_s, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise GoogleSheetsError(f"Google Sheets gviz query failed: {exc}") from exc
    if response.status_code >= 400:
        raise GoogleSheetsError(
            "Google Sheets gviz query failed (sheet must be publicly readable or link-shared)",
            status_code=response.status_code,
            body=response.text[:500],
        )
    return parse_gviz_table_response(response.text)


def query_public_spreadsheet_by_customer(
    url: str,
    customer_name: str,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> list[dict[str, Any]]:
    """Lookup appointment sheet rows for one CUSTOMER (column C) via gquery."""
    return query_public_spreadsheet_rows(
        url,
        tq_query=build_customer_gviz_query(customer_name),
        timeout_s=timeout_s,
    )


__all__ = (
    "GoogleSheetsError",
    "build_customer_gviz_query",
    "build_gviz_tq_url",
    "escape_gviz_string",
    "is_google_spreadsheet_url",
    "parse_gviz_table_response",
    "parse_spreadsheet_url",
    "query_public_spreadsheet_by_customer",
    "query_public_spreadsheet_rows",
)
