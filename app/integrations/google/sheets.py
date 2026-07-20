"""Google Sheets public export (HTTP only)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlparse

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
    for key in ("gid",):
        values = parse_qs(parsed.query).get(key)
        if values and values[0]:
            gid = str(values[0]).strip() or None
    if gid is None and parsed.fragment:
        fragment = parse_qs(parsed.fragment.lstrip("#"))
        frag_gid = fragment.get("gid")
        if frag_gid and frag_gid[0]:
            gid = str(frag_gid[0]).strip() or None

    return sheet_id, gid


def build_public_xlsx_export_url(sheet_id: str, gid: str | None = None) -> str:
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    if gid:
        url = f"{url}&gid={gid}"
    return url


def fetch_public_spreadsheet_xlsx(
    url: str,
    *,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> bytes:
    """Download a public (link-shared) spreadsheet as ``.xlsx`` bytes."""
    sheet_id, gid = parse_spreadsheet_url(url)
    export_url = build_public_xlsx_export_url(sheet_id, gid)
    try:
        response = httpx.get(export_url, timeout=timeout_s, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise GoogleSheetsError(f"Google Sheets download failed: {exc}") from exc
    if response.status_code >= 400:
        raise GoogleSheetsError(
            "Google Sheets export failed (sheet must be publicly readable or link-shared)",
            status_code=response.status_code,
            body=response.text[:500],
        )
    data = response.content
    if not data:
        raise GoogleSheetsError("Google Sheets export returned empty body")
    return data
