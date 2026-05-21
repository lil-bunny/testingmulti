"""Integration tests for the SharePoint-backed Delivery locations flow.

These tests build a tiny .xlsx workbook in memory with ``openpyxl``, patch the
SharePoint fetch, and confirm the full pipeline (bytes -> parsed envelope ->
cleaned rows -> index lookup) works end-to-end without any network or disk I/O.
"""

from __future__ import annotations

import io

import httpx
import openpyxl
import pytest

import app.services.delivery_locations_service as service_module
from app.integrations.sharepoint.excel_reader import (
    SharePointDownloadError,
    fetch_sharepoint_xlsx_bytes,
)
from app.services.delivery_locations_service import DeliveryLocationsService


def _build_delivery_locations_xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Delivery locations"
    ws.append(
        [
            "BP #",
            "delviery",
            "Name",
            "Street",
            "Zip Code",
            "City",
            "country name",
        ]
    )
    ws.append(
        [
            "41000000",
            "41000000",
            "CARRIER CLAIMS-CCX",
            "",
            "76172",
            "NORTH RICHLAND HILLS          ",
            "U.S.A.",
        ]
    )
    ws.append(
        [
            "41000100",
            "41000100",
            "CARRIER CLAIMS ABF FREIGHT",
            "1420 STEUBEN STREET",
            "51105",
            "SIOUX CITY",
            "U.S.A.",
        ]
    )
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_service_builds_index_from_sharepoint_xlsx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xlsx_bytes = _build_delivery_locations_xlsx_bytes()
    calls = {"n": 0}

    def fake_fetch(share_url: str) -> bytes:
        calls["n"] += 1
        assert share_url.startswith("https://")
        return xlsx_bytes

    monkeypatch.setattr(
        service_module, "fetch_sharepoint_xlsx_bytes", fake_fetch
    )

    svc = DeliveryLocationsService()

    hit = svc.lookup("41000100")
    assert hit is not None
    assert hit["City"] == "SIOUX CITY"
    assert str(hit["Zip Code"]) == "51105"

    cleaned = svc.lookup("41000000")
    assert cleaned is not None
    assert cleaned["City"] == "NORTH RICHLAND HILLS"

    assert svc.lookup("99999999") is None

    assert calls["n"] == 1


def test_index_for_ingest_run_returns_none_on_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_fetch(share_url: str) -> bytes:
        raise SharePointDownloadError("share link is no longer anonymous")

    monkeypatch.setattr(
        service_module, "fetch_sharepoint_xlsx_bytes", fake_fetch
    )

    svc = DeliveryLocationsService()

    assert svc.index_for_ingest_run() is None


class _FakeHttpxResponse:
    def __init__(self, status_code: int, content: bytes, content_type: str) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Type": content_type}


class _FakeHttpxClient:
    def __init__(self, response: _FakeHttpxResponse) -> None:
        self._response = response

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def get(self, url: str) -> _FakeHttpxResponse:
        assert "download=1" in url
        return self._response


def test_fetch_raises_when_response_is_html_login_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = b"<html><body>Sign in to SharePoint</body></html>"
    response = _FakeHttpxResponse(200, html, "text/html")

    def fake_client_factory(*_: object, **__: object) -> _FakeHttpxClient:
        return _FakeHttpxClient(response)

    monkeypatch.setattr(httpx, "Client", fake_client_factory)

    with pytest.raises(SharePointDownloadError) as excinfo:
        fetch_sharepoint_xlsx_bytes("https://example.sharepoint.com/share")

    assert "not an .xlsx workbook" in str(excinfo.value)


def test_fetch_raises_on_non_2xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeHttpxResponse(403, b"forbidden", "text/plain")

    def fake_client_factory(*_: object, **__: object) -> _FakeHttpxClient:
        return _FakeHttpxClient(response)

    monkeypatch.setattr(httpx, "Client", fake_client_factory)

    with pytest.raises(SharePointDownloadError) as excinfo:
        fetch_sharepoint_xlsx_bytes("https://example.sharepoint.com/share")

    assert "403" in str(excinfo.value)


def test_fetch_returns_bytes_on_valid_xlsx_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xlsx_bytes = _build_delivery_locations_xlsx_bytes()
    response = _FakeHttpxResponse(
        200,
        xlsx_bytes,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    def fake_client_factory(*_: object, **__: object) -> _FakeHttpxClient:
        return _FakeHttpxClient(response)

    monkeypatch.setattr(httpx, "Client", fake_client_factory)

    out = fetch_sharepoint_xlsx_bytes(
        "https://example.sharepoint.com/share?rtime=abc"
    )

    assert out == xlsx_bytes
